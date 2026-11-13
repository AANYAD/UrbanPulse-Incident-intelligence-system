from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from transformers import pipeline
from datetime import datetime, timedelta
import uuid, json, os, asyncio, hashlib
import smtplib, threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── EMAIL CONFIG ──────────────────────────────────────────────────────
# Fill in your Gmail credentials below OR set as environment variables.
# Use a Gmail App Password (not your real password):
# https://myaccount.google.com/apppasswords
from dotenv import load_dotenv
load_dotenv()

SMTP_EMAIL    = os.environ.get("URBANPULSE_EMAIL", "")
SMTP_PASSWORD = os.environ.get("URBANPULSE_PASSWORD", "")
SMTP_ENABLED  = bool(SMTP_EMAIL and SMTP_PASSWORD)

def send_email_async(to_email: str, subject: str, body: str):
    """Send email in a background thread — never blocks the API."""
    if not SMTP_ENABLED or not to_email:
        return
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = "UrbanPulse <{}>".format(SMTP_EMAIL)
            msg["To"]      = to_email
            msg.attach(MIMEText(body, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
                s.login(SMTP_EMAIL, SMTP_PASSWORD)
                s.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        except Exception as e:
            print("[EMAIL] Failed to send to {}: {}".format(to_email, e))
    threading.Thread(target=_send, daemon=True).start()

def make_email_html(title: str, lines: list) -> str:
    rows = "".join(
        "<tr><td style='padding:6px 12px;color:#ccc;font-size:13px;font-family:monospace;'>{}</td></tr>".format(l)
        for l in lines
    )
    return """
    <div style="background:#0a0a0a;padding:32px;font-family:monospace;max-width:520px;">
      <h2 style="color:#ff4d00;font-size:18px;margin-bottom:4px;">UrbanPulse_</h2>
      <p style="color:#555;font-size:11px;margin-bottom:20px;border-bottom:1px solid #1a1a1a;padding-bottom:12px;">
        CIVIC INCIDENT INTELLIGENCE SYSTEM
      </p>
      <h3 style="color:#e0e0e0;font-size:15px;margin-bottom:8px;">{title}</h3>
      <table style="width:100%;border-collapse:collapse;background:#111;border:1px solid #1a1a1a;">{rows}</table>
      <p style="color:#333;font-size:11px;margin-top:20px;border-top:1px solid #1a1a1a;padding-top:12px;">
        You are receiving this because you registered at UrbanPulse with this email.
      </p>
    </div>""".format(title=title, rows=rows)

def get_citizen_email(token: str) -> str:
    """Look up email for a citizen from their session token."""
    sess = sessions.get(token)
    if not sess:
        return ""
    return citizen_users.get(sess.get("username", ""), {}).get("email", "")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AI MODEL ──────────────────────────────────────────────────────────
classifier = pipeline(
    "text-classification",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

# ── PERSISTENCE ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE  = os.path.join(BASE_DIR, "data.json") if os.path.exists(os.path.join(BASE_DIR, "data.json")) else "data.json"
USERS_FILE = os.path.join(BASE_DIR, "users.json") if os.path.exists(os.path.join(BASE_DIR, "users.json")) else "users.json"

PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

@app.get("/")
def read_root():
    root_index = os.path.join(PROJECT_ROOT, "index.html")
    if os.path.exists(root_index):
        return FileResponse(root_index)
    return RedirectResponse(url="/frontend/index.html")

def load_data():
    """Load incidents from disk on startup."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_data():
    """Save all incidents to disk after every write."""
    with open(DATA_FILE, "w") as f:
        json.dump(incidents, f, indent=2, default=str)

def load_users():
    """Load citizen accounts from disk."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                data = json.load(f)
                updated = False
                for uname, udata in data.items():
                    if "user_id" not in udata:
                        udata["user_id"] = str(uuid.uuid5(uuid.NAMESPACE_OID, uname))
                        updated = True
                if updated:
                    with open(USERS_FILE, "w") as f_out:
                        json.dump(data, f_out, indent=2)
                return data
        except:
            pass
    return {}

def save_users():
    """Save citizen accounts to disk."""
    with open(USERS_FILE, "w") as f:
        json.dump(citizen_users, f, indent=2)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ── IN-MEMORY STORES (loaded from disk) ───────────────────────────────
incidents     = load_data()
citizen_users = load_users()   # { username: { password_hash, display, created_at } }
sessions      = {}             # sessions are NOT persisted (expire on restart, fine)

# SSE subscribers: list of asyncio.Queue, one per connected client
sse_subscribers: list[asyncio.Queue] = []

VALID_STATUSES = {"OPEN", "UNDER REVIEW", "IN PROGRESS", "RESOLVED"}

# Hardcoded authority users (staff accounts — not stored in users.json)
AUTHORITY_USERS = {
    "superadmin": {"password": "super123",  "role": "super_admin",   "display": "Super Admin"},
    "fire_dept":  {"password": "fire123",   "role": "dept_admin",    "display": "Fire & Rescue Dept"},
    "water_dept": {"password": "water123",  "role": "dept_admin",    "display": "Water Department"},
    "officer1":   {"password": "field123",  "role": "field_officer", "display": "Field Officer 1"},
    "admin":      {"password": "admin",     "role": "super_admin",   "display": "Admin"},
}

# ── SSE HELPERS ───────────────────────────────────────────────────────
async def broadcast(event: str, data: dict):
    """Push an SSE event to all connected clients."""
    msg = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    dead = []
    for q in sse_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        sse_subscribers.remove(q)

# ── MODELS ────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class SignupRequest(BaseModel):
    username: str
    password: str
    display:  Optional[str] = None
    email:    Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class TranslateRequest(BaseModel):
    text: str
    source_lang: str

class IncidentRequest(BaseModel):
    description: str
    category:    str
    latitude:    float
    longitude:   float
    image:       Optional[str] = None
    token:       Optional[str] = None   # citizen token to link email
    original_transcript: Optional[str] = None
    original_language:   Optional[str] = None
    input_method:        Optional[str] = "manual"

class UpdateStatusRequest(BaseModel):
    id:            str
    status:        str
    token:         str
    internal_note: Optional[str] = None

class CommentRequest(BaseModel):
    incident_id: str
    token:       str
    message:     str

class IncidentCommentRequest(BaseModel):
    token:   str
    message: str

class FlagReviewRequest(BaseModel):
    token: Optional[str] = None

class AdminReviewActionRequest(BaseModel):
    token:  str
    action: str  # "approve", "reject", "restore"

# ── KEYWORDS ─────────────────────────────────────────────────────────
HIGH_KEYWORDS   = ["fire","explosion","gas leak","unconscious","electrocuted","flood",
                   "collapse","blast","cylinder","toxic","shooting","accident","emergency"]
MEDIUM_KEYWORDS = ["pothole","waterlogging","power cut","traffic jam","blocked drain",
                   "garbage not collected","outage","overflow","broken pipe","no water"]
LOW_KEYWORDS    = ["small","minor","slight","crack","flickering","dripping","one street",
                   "small pothole","dim light","slow drain"]

DEPT_MAP = {
    "fire":       ("Fire & Rescue",   4),
    "blast":      ("Fire & Rescue",   4),
    "gas leak":   ("Fire & Rescue",   4),
    "flood":      ("Fire & Rescue",   4),
    "water":      ("Water Dept",     24),
    "drain":      ("Water Dept",     24),
    "sewer":      ("Water Dept",     24),
    "pipe":       ("Water Dept",     24),
    "power":      ("Power & Energy", 12),
    "outage":     ("Power & Energy", 12),
    "electric":   ("Power & Energy", 12),
    "road":       ("Public Works",   48),
    "pothole":    ("Public Works",   48),
    "traffic":    ("Public Works",   48),
    "garbage":    ("Sanitation Dept",48),
    "waste":      ("Sanitation Dept",48),
    "sanitation": ("Sanitation Dept",48),
}

def get_severity(text: str) -> str:
    t = text.lower()
    for kw in HIGH_KEYWORDS:
        if kw in t: return "HIGH"
    for kw in MEDIUM_KEYWORDS:
        if kw in t: return "MEDIUM"
    for kw in LOW_KEYWORDS:
        if kw in t: return "LOW"
    try:
        result = classifier(text[:512])[0]
        score  = result["score"]
        if score > 0.90: return "HIGH"
        if score > 0.75: return "MEDIUM"
        return "LOW"
    except:
        return "MEDIUM"

def get_department(text: str):
    t = text.lower()
    for kw, (dept, sla) in DEPT_MAP.items():
        if kw in t:
            return dept, sla
    return "General Services", 48

def get_session_user(token: str):
    return sessions.get(token)

def require_auth(token: str, roles: list = None):
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if roles and user["role"] not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user

def find_incident(incident_id: str):
    if not incident_id:
        return None
    target = str(incident_id).strip()
    if target in incidents:
        return incidents[target]
    target_lower = target.lower()
    for inc in incidents.values():
        if str(inc.get("id", "")).strip().lower() == target_lower or str(inc.get("ref_id", "")).strip().lower() == target_lower:
            return inc
    return None

# ── AUTH: CITIZEN SIGNUP ──────────────────────────────────────────────
@app.post("/auth/signup")
def signup(req: SignupRequest):
    username = req.username.strip().lower()
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if not req.password or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    if username in citizen_users:
        raise HTTPException(status_code=409, detail="Username already taken")
    if username in AUTHORITY_USERS:
        raise HTTPException(status_code=409, detail="Username already taken")

    # Email uniqueness check (case-insensitive)
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")

    for udata in citizen_users.values():
        existing_email = (udata.get("email") or "").strip().lower()
        if existing_email and existing_email == email:
            raise HTTPException(
                status_code=409,
                detail="An account with this email address already exists. Please log in instead."
            )

    display = req.display or req.username
    user_id = str(uuid.uuid4())
    citizen_users[username] = {
        "user_id":       user_id,
        "password_hash": hash_password(req.password),
        "display":       display,
        "role":          "citizen",
        "email":         email,
        "created_at":    datetime.now().isoformat(),
    }
    save_users()  # persist to disk

    # Welcome email
    if email:
        send_email_async(email, "Welcome to UrbanPulse", make_email_html(
            "Account Created",
            ["Username: " + username,
             "You can now submit and track civic complaints.",
             "You will receive email alerts when your complaint status changes."]
        ))

    token = str(uuid.uuid4())
    sessions[token] = {
        "user_id":  user_id,
        "username": username,
        "role":     "citizen",
        "display":  display,
        "token":    token,
    }
    return {"token": token, "role": "citizen", "display": display, "user_id": user_id}

# ── AUTH: LOGIN (authority + citizen) ────────────────────────────────
@app.post("/auth/login")
def login(req: LoginRequest):
    username = req.username.strip().lower()

    # Check authority accounts first
    auth_user = AUTHORITY_USERS.get(username) or AUTHORITY_USERS.get(req.username)
    if auth_user and auth_user["password"] == req.password:
        token = str(uuid.uuid4())
        sessions[token] = {
            "username": username,
            "role":     auth_user["role"],
            "display":  auth_user["display"],
            "token":    token,
        }
        return {"token": token, "role": auth_user["role"], "display": auth_user["display"]}

    # Check citizen accounts (supports either username or registered email)
    cit_user = citizen_users.get(username)
    if not cit_user:
        for uname, udata in citizen_users.items():
            if uname.lower() == username or (udata.get("email") or "").strip().lower() == username:
                cit_user = udata
                username = uname
                break

    if cit_user and cit_user["password_hash"] == hash_password(req.password):
        user_id = cit_user.get("user_id")
        if not user_id:
            user_id = str(uuid.uuid5(uuid.NAMESPACE_OID, username))
            cit_user["user_id"] = user_id
            save_users()
        token = str(uuid.uuid4())
        sessions[token] = {
            "user_id":  user_id,
            "username": username,
            "role":     "citizen",
            "display":  cit_user["display"],
            "token":    token,
        }
        return {"token": token, "role": "citizen", "display": cit_user["display"], "user_id": user_id}

    raise HTTPException(status_code=401, detail="Invalid username or password")

@app.post("/auth/logout")
def logout(data: dict):
    sessions.pop(data.get("token", ""), None)
    return {"ok": True}

@app.get("/auth/me")
def me(token: str):
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

# ── AUTH: FORGOT & RESET PASSWORD ─────────────────────────────────────
password_resets = {}  # { token_hash: { "username": str, "email": str, "expires": datetime } }

@app.post("/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    # Generic response returned regardless of account existence to prevent account enumeration
    generic_msg = "If this email is registered, a password reset link has been sent to it."

    user_entry = None
    for uname, udata in citizen_users.items():
        if (udata.get("email") or "").strip().lower() == email:
            user_entry = (uname, udata)
            break

    if not user_entry:
        return {"ok": True, "message": generic_msg}

    import secrets
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires = datetime.now() + timedelta(minutes=15)
    password_resets[token_hash] = {
        "username": user_entry[0],
        "email": email,
        "expires": expires
    }

    reset_link = f"http://127.0.0.1:5500/frontend/index.html?reset_token={raw_token}"

    send_email_async(
        email,
        "UrbanPulse — Password Reset Link",
        make_email_html("Password Reset Request", [
            "We received a request to reset your UrbanPulse password for account: <b>" + user_entry[0] + "</b>",
            "Click the button below to set a new password:",
            "<div style='text-align:center;margin:18px 0;'><a href='" + reset_link + "' style='background:#ff4d00;color:#fff;padding:10px 22px;text-decoration:none;font-weight:bold;font-size:13px;letter-spacing:1px;display:inline-block;'>RESET PASSWORD</a></div>",
            "Or open this link directly:<br><span style='font-size:11px;color:#888;word-break:break-all;'>" + reset_link + "</span>",
            "This link will expire in 15 minutes and can only be used once.",
            "If you did not request this, you can safely ignore this email."
        ])
    )

    return {"ok": True, "message": generic_msg}

@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
    if not req.token:
        raise HTTPException(status_code=400, detail="Reset token is required")
    if not req.new_password or len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")

    token_hash = hashlib.sha256(req.token.strip().encode("utf-8")).hexdigest()
    record = password_resets.get(token_hash)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or already used password reset link")

    if datetime.now() > record["expires"]:
        password_resets.pop(token_hash, None)
        raise HTTPException(status_code=400, detail="Password reset link has expired. Please request a new one.")

    username = record["username"]
    if username not in citizen_users:
        found_uname = None
        for u in citizen_users.keys():
            if u.lower() == username.lower():
                found_uname = u
                break
        if found_uname:
            username = found_uname
        else:
            password_resets.pop(token_hash, None)
            raise HTTPException(status_code=404, detail="Account not found")

    citizen_users[username]["password_hash"] = hash_password(req.new_password)
    save_users()

    # Single-use: remove immediately
    password_resets.pop(token_hash, None)

    # Invalidate active sessions for this user
    invalid_tokens = [tok for tok, s in sessions.items() if s.get("username") == username]
    for tok in invalid_tokens:
        sessions.pop(tok, None)

    return {
        "ok": True,
        "message": f"Password reset successfully for account '{username}'. Please log in with your new password.",
        "username": username
    }

# ── PLACE SEARCH (GEOCODING) ──────────────────────────────────────────
place_search_cache = {}

@app.get("/api/places/search")
def search_places(q: str = ""):
    query = (q or "").strip()
    if len(query) < 2:
        return []
    q_lower = query.lower()
    if q_lower in place_search_cache:
        return place_search_cache[q_lower]
    try:
        import urllib.request
        import urllib.parse
        encoded_q = urllib.parse.quote(query)
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={encoded_q}&limit=6&addressdetails=1"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "UrbanPulse-CivicPlatform/2.0 (civic-incident-response)",
                "Accept-Language": "en"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in data:
                results.append({
                    "name": item.get("name") or (item.get("display_name", "").split(",")[0]),
                    "display_name": item.get("display_name", ""),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type", "")
                })
            place_search_cache[q_lower] = results
            return results
    except Exception as e:
        print(f"Geocoding error: {e}")
        return []

# ── SSE: REAL-TIME STREAM ─────────────────────────────────────────────
@app.get("/stream")
async def stream():
    """
    Server-Sent Events endpoint.
    Frontend connects once and receives live pushes on every change.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sse_subscribers.append(queue)

    async def event_generator():
        # Send a welcome ping so client knows connection is alive
        yield "event: connected\ndata: {\"msg\": \"stream ready\"}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield msg
                except asyncio.TimeoutError:
                    # Send keepalive comment every 25s to prevent proxy timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in sse_subscribers:
                sse_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        }
    )

# ── MULTILINGUAL TRANSLATION ──────────────────────────────────────────
@app.post("/api/translate")
async def translate_text(req: TranslateRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text to translate cannot be empty.")
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail="Text exceeds maximum limit of 1000 characters.")

    from app.translation_service import IndicTranslationService
    try:
        service = IndicTranslationService.get_instance()
        # Execute translation in thread to avoid blocking FastAPI event loop
        result = await asyncio.to_thread(service.translate, text, req.source_lang)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print(f"[TRANSLATION ERROR] {e}")
        raise HTTPException(status_code=503, detail=f"Translation service temporarily unavailable: {str(e)}")

# ── CITIZEN: SUBMIT ───────────────────────────────────────────────────
@app.post("/classify")
async def classify(req: IncidentRequest):
    severity           = get_severity(req.description)
    department, sla_h  = get_department(req.description)
    if severity == "HIGH":
        sla_h = max(4, sla_h // 2)

    now     = datetime.now()
    sla_due = now + timedelta(hours=sla_h)
    ref_id  = "INC-" + str(uuid.uuid4())[:8].upper()
    inc_id  = str(uuid.uuid4())

    # Look up submitter email and user_id if token provided
    submitter_email = ""
    user_id = None
    if req.token:
        sess = get_session_user(req.token)
        if sess:
            user_id = sess.get("user_id")
            uname = sess.get("username", "")
            submitter_email = citizen_users.get(uname, {}).get("email", "")

    incidents[inc_id] = {
        "id":                  inc_id,
        "ref_id":              ref_id,
        "user_id":             user_id,
        "description":         req.description,
        "category":            req.category,
        "latitude":            req.latitude,
        "longitude":           req.longitude,
        "severity":            severity,
        "status":              "OPEN",
        "department":          department,
        "sla_due":             sla_due.isoformat(),
        "sla_hours":           sla_h,
        "created_at":          now.isoformat(),
        "resolved_at":         None,
        "image":               req.image,
        "comments":            [],
        "history":             [{"status": "OPEN", "time": now.isoformat(), "by": "system"}],
        "submitter_email":     submitter_email,
        "original_transcript": req.original_transcript,
        "original_language":   req.original_language,
        "input_method":        req.input_method or "manual",
    }

    # Confirm submission to citizen
    if submitter_email:
        send_email_async(submitter_email, "Complaint Submitted — " + ref_id,
            make_email_html("Complaint Received", [
                "Reference ID: <b style='color:#ff4d00;'>" + ref_id + "</b>",
                "Category: " + req.category,
                "Severity: " + severity,
                "Routed to: " + department,
                "SLA: " + str(sla_h) + " hours",
                "Save your Reference ID to track your complaint.",
            ])
        )
    save_data()  # persist

    # Broadcast new incident to all SSE clients
    await broadcast("new_incident", {
        "id":         inc_id,
        "ref_id":     ref_id,
        "category":   req.category,
        "severity":   severity,
        "department": department,
        "status":     "OPEN",
    })

    return {"id": inc_id, "ref_id": ref_id, "severity": severity,
            "department": department, "sla_hours": sla_h, "status": "OPEN"}

# ── CITIZEN: TRACK ────────────────────────────────────────────────────
@app.get("/track/{ref_id}")
def track(ref_id: str):
    inc = find_incident(ref_id)
    if inc:
        return {
            "id":                  inc["id"],
            "ref_id":              inc["ref_id"],
            "status":              inc["status"],
            "severity":            inc["severity"],
            "department":          inc["department"],
            "description":         inc.get("description", ""),
            "created_at":          inc["created_at"],
            "resolved_at":         inc["resolved_at"],
            "history":             inc.get("history", []),
            "comments":            [c for c in inc.get("comments", []) if not c.get("internal")],
            "original_transcript": inc.get("original_transcript"),
            "original_language":   inc.get("original_language"),
            "input_method":        inc.get("input_method", "manual"),
            "review_status":       inc.get("review_status"),
            "review_requested_by": inc.get("review_requested_by"),
            "review_requested_at": inc.get("review_requested_at"),
            "review_decision":     inc.get("review_decision"),
            "is_removed":          inc.get("is_removed", False),
        }
    raise HTTPException(status_code=404, detail="Incident not found")

# ── CITIZEN: MY SUBMITTED REPORTS ─────────────────────────────────────
@app.get("/incidents/my")
@app.get("/incidents/my/")
def get_my_incidents(token: str, status: Optional[str] = None, sort: Optional[str] = None):
    user = require_auth(token)
    user_id = user.get("user_id")
    if not user_id:
        return []

    # Strictly filter by authenticated citizen user_id at the backend/database level
    my_reports = [
        i for i in incidents.values()
        if i.get("user_id") and i.get("user_id") == user_id
    ]

    if status:
        st_lower = status.strip().lower()
        if st_lower == "active":
            my_reports = [
                i for i in my_reports
                if (i.get("status") or "").upper() != "RESOLVED" and not i.get("resolved_at")
            ]
        elif st_lower == "resolved":
            my_reports = [
                i for i in my_reports
                if (i.get("status") or "").upper() == "RESOLVED" or i.get("resolved_at")
            ]

    reverse = (sort or "newest").strip().lower() != "oldest"
    my_reports.sort(key=lambda x: x.get("created_at", ""), reverse=reverse)
    return my_reports

# ── CITIZEN: FLAG INCIDENT FOR REVIEW ─────────────────────────────────
@app.post("/incidents/{incident_id}/flag-review")
@app.post("/incidents/{incident_id}/flag-review/")
async def flag_incident_for_review(incident_id: str, req: Optional[FlagReviewRequest] = None, token: Optional[str] = None):
    auth_token = (req.token if req and req.token else None) or token
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication token required")
    user = require_auth(auth_token)

    inc = find_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    user_id = user.get("user_id")
    if not user_id or inc.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Users can only flag their own incidents")

    # Prevent duplicate pending review requests
    if inc.get("review_status") == "pending":
        raise HTTPException(status_code=400, detail="A review request is already pending for this incident")

    now_iso = datetime.now().isoformat()
    requested_by = user.get("username") or user.get("display") or "citizen"

    # Store review metadata without altering classification, severity, department, SLA, description or deleting
    inc["review_status"] = "pending"
    inc["review_requested_by"] = requested_by
    inc["review_requested_at"] = now_iso
    if "is_removed" not in inc:
        inc["is_removed"] = False

    inc.setdefault("history", []).append({
        "status": inc["status"],
        "time": now_iso,
        "by": f"{user.get('display', requested_by)} (Flagged for Review)"
    })

    save_data()

    await broadcast("review_requested", {
        "id": inc["id"],
        "ref_id": inc["ref_id"],
        "review_status": "pending",
        "review_requested_by": requested_by,
        "review_requested_at": now_iso
    })

    return {
        "ok": True,
        "message": "Incident flagged for review successfully",
        "incident": inc
    }

# ── PUBLIC: HEATMAP + STATS ───────────────────────────────────────────
@app.get("/public/heatmap")
def public_heatmap():
    return [
        {"latitude": i["latitude"], "longitude": i["longitude"],
         "severity": i["severity"], "category": i["category"],
         "status": i["status"], "created_at": i["created_at"],
         "description": i.get("description","")}
        for i in incidents.values()
        if not i.get("is_removed", False)
    ]

@app.get("/public/stats")
def public_stats():
    all_inc = [i for i in incidents.values() if not i.get("is_removed", False)]
    cats = {}
    for i in all_inc:
        c = i.get("category", "Other")
        cats[c] = cats.get(c, 0) + 1
    return {
        "total":        len(all_inc),
        "open":         sum(1 for i in all_inc if i["status"] == "OPEN"),
        "under_review": sum(1 for i in all_inc if i["status"] == "UNDER REVIEW"),
        "in_progress":  sum(1 for i in all_inc if i["status"] == "IN PROGRESS"),
        "resolved":     sum(1 for i in all_inc if i["status"] == "RESOLVED"),
        "by_category":  cats,
    }

# ── ADMIN: LIST + FILTER ──────────────────────────────────────────────
@app.get("/incidents")
def get_incidents(
    status:          Optional[str] = None,
    severity:        Optional[str] = None,
    department:      Optional[str] = None,
    category:        Optional[str] = None,
    search:          Optional[str] = None,
    date_from:       Optional[str] = None,
    date_to:         Optional[str] = None,
    area:            Optional[str] = None,
    include_removed: Optional[bool] = False,
):
    result = list(incidents.values())
    if not include_removed:
        result = [i for i in result if not i.get("is_removed", False)]
    if status:    result = [i for i in result if i["status"] == status.upper()]
    if severity:  result = [i for i in result if i["severity"] == severity.upper()]
    if department:result = [i for i in result if i.get("department","").lower() == department.lower()]
    if category:  result = [i for i in result if category.lower() in i.get("category","").lower()]
    if search:
        q = search.lower()
        result = [i for i in result if q in i.get("description","").lower()
                  or q in i.get("ref_id","").lower()]
    if area:
        a = area.lower()
        result = [i for i in result if a in i.get("description","").lower()]
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            result = [i for i in result if i.get("created_at")
                      and datetime.fromisoformat(i["created_at"]) >= df]
        except: pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59)
            result = [i for i in result if i.get("created_at")
                      and datetime.fromisoformat(i["created_at"]) <= dt]
        except: pass
    result.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return result

# ── ADMIN: INCIDENT REMOVAL REQUESTS ──────────────────────────────────
@app.get("/admin/removal-requests")
@app.get("/admin/removal-requests/")
def get_removal_requests(token: str):
    admin_user = require_auth(token, roles=["super_admin", "dept_admin", "field_officer"])

    requests = []
    for inc in incidents.values():
        rev_status = inc.get("review_status")
        is_rem = inc.get("is_removed", False)
        if rev_status or is_rem:
            submitting_user = inc.get("review_requested_by")
            if not submitting_user and inc.get("user_id"):
                for uname, udata in citizen_users.items():
                    if udata.get("user_id") == inc.get("user_id"):
                        submitting_user = udata.get("display") or uname
                        break
            if not submitting_user:
                submitting_user = "Unknown"

            inc_copy = dict(inc)
            inc_copy["submitting_user"] = submitting_user
            requests.append(inc_copy)

    requests.sort(key=lambda x: x.get("review_requested_at") or x.get("created_at") or "", reverse=True)
    return requests

# ── ADMIN: PROCESS REVIEW ACTION (APPROVE / REJECT / RESTORE) ──────────
@app.post("/admin/incidents/{incident_id}/review")
@app.post("/admin/incidents/{incident_id}/review/")
@app.post("/incidents/{incident_id}/review")
@app.post("/incidents/{incident_id}/review/")
async def review_incident_action(incident_id: str, req: AdminReviewActionRequest):
    admin_user = require_auth(req.token, roles=["super_admin", "dept_admin", "field_officer"])

    inc = find_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    action = req.action.lower().strip()
    now_iso = datetime.now().isoformat()
    decided_by = admin_user.get("display") or admin_user.get("username") or "Admin"

    if action == "approve":
        inc["review_status"] = "approved"
        inc["is_removed"] = True
        inc["review_decision"] = "approved"
        inc["review_decided_by"] = decided_by
        inc["review_decided_at"] = now_iso
        inc.setdefault("history", []).append({
            "status": inc["status"],
            "time": now_iso,
            "by": f"{decided_by} (Removal Approved)"
        })
    elif action == "reject":
        inc["review_status"] = "rejected"
        inc["is_removed"] = False
        inc["review_decision"] = "rejected"
        inc["review_decided_by"] = decided_by
        inc["review_decided_at"] = now_iso
        inc.setdefault("history", []).append({
            "status": inc["status"],
            "time": now_iso,
            "by": f"{decided_by} (Removal Request Rejected)"
        })
    elif action == "restore":
        inc["review_status"] = "restored"
        inc["is_removed"] = False
        inc["review_decision"] = "restored"
        inc["review_decided_by"] = decided_by
        inc["review_decided_at"] = now_iso
        inc.setdefault("history", []).append({
            "status": inc["status"],
            "time": now_iso,
            "by": f"{decided_by} (Incident Restored)"
        })
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve', 'reject', or 'restore'")

    save_data()

    await broadcast("review_updated", {
        "id": inc["id"],
        "ref_id": inc["ref_id"],
        "review_status": inc["review_status"],
        "is_removed": inc.get("is_removed", False),
        "action": action,
        "decided_by": decided_by,
        "decided_at": now_iso
    })

    return {
        "ok": True,
        "action": action,
        "incident": inc
    }

# ── ADMIN: UPDATE STATUS ──────────────────────────────────────────────
@app.post("/update")
async def update_status(req: UpdateStatusRequest):
    user = require_auth(req.token, roles=["super_admin","dept_admin","field_officer"])
    inc  = incidents.get(req.id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    new_status = req.status.upper()
    if new_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status")

    inc["status"] = new_status
    now = datetime.now().isoformat()
    inc.setdefault("history", []).append({"status": new_status, "time": now, "by": user["display"]})

    if new_status == "RESOLVED":
        inc["resolved_at"] = now
        inc["resolved_by"] = user["display"]
    else:
        inc["resolved_at"] = None
        inc.pop("resolved_by", None)

    if req.internal_note:
        inc["comments"].append({
            "id": str(uuid.uuid4())[:8], "author": user["display"],
            "role": user["role"], "message": req.internal_note,
            "internal": True, "time": now,
        })

    save_data()  # persist

    # Email the citizen whose complaint was updated
    # Find the incident submitter by checking if any citizen token matches
    for uname, udata in citizen_users.items():
        # We don't store who submitted which incident, so notify all who tracked this ref_id
        # Best effort: if incident has a submitter_token field use it
        pass
    submitter_email = inc.get("submitter_email", "")
    if submitter_email:
        status_colors = {"OPEN":"#ff4d00","UNDER REVIEW":"#ffcc00","IN PROGRESS":"#00aaff","RESOLVED":"#00ff9d"}
        send_email_async(submitter_email, "Update on your complaint " + inc["ref_id"],
            make_email_html("Complaint Status Updated", [
                "Reference ID: " + inc["ref_id"],
                "New Status: <span style='color:{};font-weight:bold;'>{}</span>".format(
                    status_colors.get(new_status, "#aaa"), new_status),
                "Updated by: " + user["display"],
                "Category: " + inc.get("category",""),
                "Description: " + inc.get("description","")[:80],
            ])
        )

    # Broadcast status change to all SSE clients
    await broadcast("status_update", {
        "id":         inc["id"],
        "ref_id":     inc["ref_id"],
        "status":     new_status,
        "updated_by": user["display"],
        "time":       now,
    })

    return inc

# ── COMMENT & DISCUSSION ──────────────────────────────────────────────
def validate_comment_message(msg: str) -> str:
    if not msg or not isinstance(msg, str):
        raise HTTPException(status_code=400, detail="Comment message cannot be empty")
    cleaned = msg.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Comment message cannot be empty or whitespace only")
    if len(cleaned) > 2000:
        raise HTTPException(status_code=400, detail="Comment message cannot exceed 2000 characters")
    return cleaned

async def handle_add_comment(incident_identifier: str, token: str, raw_message: str):
    inc = find_incident(incident_identifier)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    message = validate_comment_message(raw_message)

    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required to post comments")

    role = user.get("role", "citizen")
    is_admin = role in ["super_admin", "dept_admin", "field_officer"]

    if not is_admin:
        # Strict ownership check for citizen
        user_id = user.get("user_id")
        inc_user_id = inc.get("user_id")
        if not user_id or inc_user_id != user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You can only comment on your own incidents")
        sender_role = "citizen"
        sender_id = user_id
    else:
        sender_role = "admin"
        sender_id = user.get("username", "admin")

    author = user.get("display") or user.get("username") or ("Administrator" if is_admin else "Citizen")
    now_iso = datetime.now().isoformat()
    comment_id = str(uuid.uuid4())[:8]

    comment = {
        "id": comment_id,
        "comment_id": comment_id,
        "message": message,
        "author": author,
        "sender_id": sender_id,
        "sender_role": sender_role,
        "role": role,
        "created_at": now_iso,
        "time": now_iso,
        "internal": False,
    }

    if "comments" not in inc or not isinstance(inc["comments"], list):
        inc["comments"] = []
    inc["comments"].append(comment)
    save_data()  # persist to disk

    # Email citizen if an authority replied publicly
    if sender_role == "admin":
        submitter_email = inc.get("submitter_email", "")
        if submitter_email:
            send_email_async(submitter_email, "Authority replied on " + inc["ref_id"],
                make_email_html("New Reply on Your Complaint", [
                    "Reference ID: " + inc["ref_id"],
                    "Reply from: " + author,
                    "Message: " + message,
                    "Current Status: " + inc.get("status",""),
                ])
            )

    # Broadcast new comment to all SSE clients
    await broadcast("new_comment", {
        "incident_id": inc["id"],
        "ref_id":      inc["ref_id"],
        "comment_id":  comment_id,
        "author":      author,
        "sender_role": sender_role,
        "role":        role,
        "message":     message,
        "created_at":  now_iso,
        "time":        now_iso,
    })

    return comment

@app.post("/incidents/{incident_id}/comments")
@app.post("/incidents/{incident_id}/comments/")
async def add_incident_comment(incident_id: str, req: IncidentCommentRequest):
    return await handle_add_comment(incident_id, req.token, req.message)

@app.post("/comment")
async def add_comment(req: CommentRequest):
    return await handle_add_comment(req.incident_id, req.token, req.message)

@app.get("/incidents/{incident_id}/comments")
@app.get("/incidents/{incident_id}/comments/")
def get_incident_comments(incident_id: str, token: str):
    inc = find_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    role = user.get("role", "citizen")
    is_admin = role in ["super_admin", "dept_admin", "field_officer"]

    if not is_admin:
        user_id = user.get("user_id")
        if not user_id or inc.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You cannot view comments for other users' incidents")

    comments = [c for c in inc.get("comments", []) if not c.get("internal")]
    comments.sort(key=lambda c: c.get("created_at") or c.get("time") or "")
    return comments

@app.get("/admin/discussions")
@app.get("/admin/discussions/")
def get_admin_discussions(token: str, filter_status: Optional[str] = None):
    require_auth(token, roles=["super_admin", "dept_admin", "field_officer"])

    discussions = []
    for inc in incidents.values():
        comments = [c for c in inc.get("comments", []) if not c.get("internal")]
        if not comments:
            continue

        comments.sort(key=lambda c: c.get("created_at") or c.get("time") or "")
        last_c = comments[-1]
        has_unanswered = (last_c.get("sender_role") == "citizen" or last_c.get("role") == "citizen")

        if filter_status == "unanswered" and not has_unanswered:
            continue

        discussions.append({
            "id": inc["id"],
            "ref_id": inc["ref_id"],
            "description": inc.get("description", ""),
            "category": inc.get("category", ""),
            "status": inc.get("status", ""),
            "severity": inc.get("severity", ""),
            "department": inc.get("department", ""),
            "created_at": inc.get("created_at", ""),
            "comments": comments,
            "total_comments": len(comments),
            "last_comment": last_c,
            "has_unanswered": has_unanswered,
            "user_id": inc.get("user_id"),
        })

    def sort_key(d):
        unans_weight = 0 if d["has_unanswered"] else 1
        last_time = d["last_comment"].get("created_at") or d["last_comment"].get("time") or ""
        try:
            ts = -datetime.fromisoformat(last_time).timestamp()
        except Exception:
            ts = 0
        return (unans_weight, ts)

    try:
        discussions.sort(key=sort_key)
    except Exception:
        discussions.sort(key=lambda d: 0 if d["has_unanswered"] else 1)

    return discussions

# ── ANALYTICS ────────────────────────────────────────────────────────
@app.get("/analytics")
def analytics(token: str):
    require_auth(token, roles=["super_admin","dept_admin"])
    all_inc = list(incidents.values())

    by_severity = {"HIGH":0,"MEDIUM":0,"LOW":0}
    by_status   = {"OPEN":0,"UNDER REVIEW":0,"IN PROGRESS":0,"RESOLVED":0}
    by_dept     = {}
    by_category = {}
    resolution_times = []

    for i in all_inc:
        by_severity[i.get("severity","LOW")] = by_severity.get(i.get("severity","LOW"),0) + 1
        st = i.get("status","OPEN")
        by_status[st] = by_status.get(st, 0) + 1
        dept = i.get("department","Unknown")
        by_dept[dept] = by_dept.get(dept, 0) + 1
        cat  = i.get("category","Unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        if i.get("resolved_at") and i.get("created_at"):
            try:
                t1 = datetime.fromisoformat(i["created_at"])
                t2 = datetime.fromisoformat(i["resolved_at"])
                resolution_times.append((t2-t1).total_seconds()/3600)
            except: pass

    resolved_count = by_status.get("RESOLVED", 0)
    avg_res = round(sum(resolution_times)/len(resolution_times),1) if resolution_times else 0
    sla_breaches = sum(
        1 for i in all_inc
        if i["status"] != "RESOLVED" and i.get("sla_due")
        and datetime.now() > datetime.fromisoformat(i["sla_due"])
    )

    return {
        "total":              len(all_inc),
        "by_severity":        by_severity,
        "by_status":          by_status,
        "by_department":      by_dept,
        "by_category":        by_category,
        "avg_resolution_hrs": avg_res,
        "sla_breaches":       sla_breaches,
        "resolution_rate":    round(resolved_count/len(all_inc)*100,1) if all_inc else 0,
    }