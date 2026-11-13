import { classifyIncident } from "./api.js";

// Voice Input State
window.hasUsedVoiceInput = false;
window.lastVoiceLanguage = null;
let speechRecognizer = null;
let isListening = false;

window.onVoiceLangChange = function() {
    const langSelect = document.getElementById("voiceLangSelect");
    const lang = langSelect ? langSelect.value : "en-IN";
    const hindiContainer = document.getElementById("hindiTranscriptContainer");
    const hindiInput = document.getElementById("hindiTranscript");
    
    // If switching back to English and no Hindi text was saved, hide Hindi container
    if (lang === "en-IN" && (!hindiInput || !hindiInput.value.trim())) {
        if (hindiContainer) hindiContainer.style.display = "none";
    }
};

window.toggleVoiceInput = function() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("Voice speech recognition is not supported in this browser. Please use Google Chrome, Microsoft Edge, or another Web Speech API compatible browser.");
        return;
    }

    const voiceBtn = document.getElementById("voiceBtn");
    const voiceBtnText = document.getElementById("voiceBtnText");
    const voiceBadge = document.getElementById("voiceStatusBadge");
    const langSelect = document.getElementById("voiceLangSelect");
    const targetLang = langSelect ? langSelect.value : "en-IN";

    if (isListening) {
        if (speechRecognizer) {
            speechRecognizer.stop();
        }
        return;
    }

    try {
        speechRecognizer = new SpeechRecognition();
        speechRecognizer.lang = targetLang;
        speechRecognizer.continuous = false;
        speechRecognizer.interimResults = false;
        speechRecognizer.maxAlternatives = 1;

        speechRecognizer.onstart = function() {
            isListening = true;
            if (voiceBadge) {
                voiceBadge.style.display = "inline-block";
                voiceBadge.innerText = "LISTENING (" + (targetLang === "hi-IN" ? "हिंदी" : "EN") + ")...";
                voiceBadge.style.color = "#ff4d00";
                voiceBadge.style.background = "#2a1208";
                voiceBadge.style.border = "1px solid #ff4d00";
            }
            if (voiceBtn) {
                voiceBtn.style.background = "#ff4d00";
                voiceBtn.style.borderColor = "#ff4d00";
                voiceBtn.style.color = "#ffffff";
            }
            if (voiceBtnText) {
                voiceBtnText.innerText = "LISTENING... (CLICK TO STOP)";
            }
        };

        speechRecognizer.onresult = function(event) {
            const transcript = event.results[0][0].transcript.trim();
            if (!transcript) return;

            window.hasUsedVoiceInput = true;
            window.lastVoiceLanguage = targetLang;

            if (targetLang === "hi-IN") {
                const hindiContainer = document.getElementById("hindiTranscriptContainer");
                const hindiInput = document.getElementById("hindiTranscript");
                const descInput = document.getElementById("desc");

                if (hindiContainer) hindiContainer.style.display = "block";
                if (hindiInput) hindiInput.value = transcript;
                if (descInput) {
                    descInput.focus();
                }

                if (voiceBadge) {
                    voiceBadge.innerText = "HINDI CAPTURED ✓";
                    voiceBadge.style.color = "#00ff9d";
                    voiceBadge.style.background = "#0c2818";
                    voiceBadge.style.border = "1px solid #00ff9d";
                }
            } else {
                // English direct input
                const descInput = document.getElementById("desc");
                const hindiContainer = document.getElementById("hindiTranscriptContainer");
                const hindiInput = document.getElementById("hindiTranscript");

                if (hindiContainer) hindiContainer.style.display = "none";
                if (hindiInput) hindiInput.value = "";
                if (descInput) {
                    descInput.value = transcript;
                    descInput.focus();
                }

                if (voiceBadge) {
                    voiceBadge.innerText = "ENGLISH CAPTURED ✓";
                    voiceBadge.style.color = "#00ff9d";
                    voiceBadge.style.background = "#0c2818";
                    voiceBadge.style.border = "1px solid #00ff9d";
                }
            }
        };

        speechRecognizer.onerror = function(event) {
            console.warn("Speech recognition error:", event.error);
            isListening = false;
            if (voiceBadge) {
                voiceBadge.style.display = "inline-block";
                if (event.error === "not-allowed" || event.error === "service-not-allowed") {
                    voiceBadge.innerText = "MIC PERMISSION DENIED";
                    alert("Microphone access was denied. Please allow microphone permissions in your browser address bar.");
                } else if (event.error === "no-speech") {
                    voiceBadge.innerText = "NO SPEECH DETECTED";
                } else if (event.error === "network") {
                    voiceBadge.innerText = "NETWORK ERROR";
                } else {
                    voiceBadge.innerText = ("ERROR: " + event.error).toUpperCase();
                }
                voiceBadge.style.color = "#ff4d00";
                voiceBadge.style.background = "#2a1208";
                voiceBadge.style.border = "1px solid #ff4d00";
            }
        };

        speechRecognizer.onend = function() {
            isListening = false;
            if (voiceBtn) {
                voiceBtn.style.background = "#1b1b1b";
                voiceBtn.style.borderColor = "#3a3a3a";
                voiceBtn.style.color = "#ffffff";
            }
            if (voiceBtnText) {
                voiceBtnText.innerText = window.hasUsedVoiceInput ? "RECORD VOICE AGAIN" : "START VOICE RECORDING";
            }
        };

        speechRecognizer.start();

    } catch (err) {
        console.error("Speech recognition startup error:", err);
        isListening = false;
        alert("Could not start voice recognition: " + err.message);
    }
};

window.handleReport = async function (e) {
    e.preventDefault();

    const desc           = document.getElementById("desc").value.trim();
    const category       = document.getElementById("incidentType").value;
    const hindiInput     = document.getElementById("hindiTranscript");
    const originalTranscript = (hindiInput && hindiInput.value.trim()) ? hindiInput.value.trim() : null;

    // Dual-channel validation:
    // If citizen used Hindi voice or entered a Hindi transcript, an English description is required
    // so DistilBERT can classify severity and route accurately without translation errors
    if (originalTranscript && !desc) {
        alert("Please provide the English Complaint Description below. This is required for AI severity assessment and department routing.");
        document.getElementById("desc").focus();
        return;
    }

    if (!desc) {
        alert("Please enter a description.");
        return;
    }

    // Determine metadata
    let inputMethod = "manual";
    let originalLanguage = null;

    if (originalTranscript) {
        inputMethod = "voice";
        originalLanguage = "hi-IN";
    } else if (window.hasUsedVoiceInput) {
        inputMethod = "voice";
        originalLanguage = window.lastVoiceLanguage || "en-IN";
    }

    // Validate coordinates
    let latitude  = null;
    let longitude = null;
    const locationInput = document.getElementById("locationInput").value.trim();
    if (locationInput) {
        const parts = locationInput.split(",");
        if (parts.length === 2) {
            const parsedLat = parseFloat(parts[0]);
            const parsedLng = parseFloat(parts[1]);
            if (!isNaN(parsedLat) && !isNaN(parsedLng) && parsedLat >= -90 && parsedLat <= 90 && parsedLng >= -180 && parsedLng <= 180) {
                latitude  = parsedLat;
                longitude = parsedLng;
            }
        }
    }

    if (latitude === null || longitude === null) {
        alert("Please set a valid incident location using Live GPS or Place Search / Manual Coordinates.");
        const locStatus = document.getElementById('locStatus');
        if (locStatus) {
            locStatus.innerText = "LOCATION REQUIRED BEFORE TRANSMITTING";
            locStatus.style.color = "var(--accent-color)";
        }
        return;
    }

    // Read image as base64 if uploaded
    let imageBase64 = null;
    const fileInput = document.getElementById("evidenceFile");
    if (fileInput && fileInput.files && fileInput.files[0]) {
        imageBase64 = await toBase64(fileInput.files[0]);
    }

    try {
        const btn     = document.getElementById("submitBtn");
        const btnText = document.getElementById("btnText");
        btnText.innerText          = "TRANSMITTING...";
        btn.style.backgroundColor  = "#ff4d00";
        btn.style.color            = "white";

        let fullDesc = desc;
        if (window.selectedPlaceName && !fullDesc.toLowerCase().includes(window.selectedPlaceName.toLowerCase().substring(0, 20))) {
            fullDesc = fullDesc + ` [Location: ${window.selectedPlaceName}]`;
        }

        // Classify + save incident (description, category, coords, image, voice metadata)
        const ai = await classifyIncident(
            fullDesc,
            category,
            latitude,
            longitude,
            imageBase64,
            originalTranscript,
            originalLanguage,
            inputMethod
        );

        btnText.innerText = "SENT ✓";
        btn.style.backgroundColor = "#00ff9d";
        btn.style.color           = "black";

        setTimeout(() => {
            showDialog(
                "TRANSMISSION COMPLETE",
                `Incident filed successfully.\n\nReference ID: ${ai.ref_id}\nSeverity: ${ai.severity}\nRouted to: ${ai.department}\nSLA: ${ai.sla_hours}h\n\nSave this ID to track your report.`,
                "success"
            );
            // Reset form
            document.querySelector("form").reset();
            const hindiContainer = document.getElementById("hindiTranscriptContainer");
            if (hindiContainer) hindiContainer.style.display = "none";
            if (hindiInput) hindiInput.value = "";
            window.hasUsedVoiceInput = false;
            window.lastVoiceLanguage = null;

            const voiceBadge = document.getElementById("voiceStatusBadge");
            if (voiceBadge) voiceBadge.style.display = "none";
            const voiceBtnTextEl = document.getElementById("voiceBtnText");
            if (voiceBtnTextEl) voiceBtnTextEl.innerText = "START VOICE RECORDING";

            const dropZone = document.getElementById('dropZone');
            if (dropZone) dropZone.classList.remove('has-image');
            const preview = document.getElementById('previewImg');
            if (preview) preview.style.display = 'none';
            const fileLabel = document.querySelector('.file-label-text');
            if (fileLabel) fileLabel.style.display = 'block';
            const locStatus = document.getElementById('locStatus');
            if (locStatus) { locStatus.innerText = "WAITING FOR SATELLITE..."; locStatus.style.color = "#666"; }
            btnText.innerText             = "Transmit Data";
            btn.style.backgroundColor     = "white";
            btn.style.color               = "black";

            renderTrackingPanel();
        }, 800);

    } catch (err) {
        console.error("Submission error:", err);
        const btn     = document.getElementById("submitBtn");
        const btnText = document.getElementById("btnText");
        btnText.innerText             = "Transmit Data";
        btn.style.backgroundColor     = "white";
        btn.style.color               = "black";
        alert("Error submitting report: " + err.message);
    }
};

// Convert file to base64
function toBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload  = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

// ── STATUS COLOR HELPER ───────────────────────────────────────────────
function statusColor(s) {
    if (s === "RESOLVED")    return "#00ff9d";
    if (s === "IN PROGRESS") return "#00aaff";
    if (s === "UNDER REVIEW")return "#ffcc00";
    return "#ff4d00"; // OPEN
}

// ── TRACKING PANEL ────────────────────────────────────────────────────
function renderTrackingPanel() {
    if (window.renderTrackingPanel) {
        window.renderTrackingPanel();
    }
}

window.checkStatus = async function(refId) {
    const el = document.getElementById(`status-${refId}`);
    el.innerHTML = '<span class="mono" style="font-size:0.7rem;color:#666;">CHECKING...</span>';

    try {
        const res = await fetch(`http://127.0.0.1:8000/track/${refId}`);
        if (!res.ok) throw new Error("Not found");
        const data = await res.json();

        const sc  = statusColor(data.status);
        const sev = data.severity === "HIGH" ? "#ff4d00" : data.severity === "MEDIUM" ? "#ffcc00" : "#00bfff";

        // Build history timeline
        const historyHtml = (data.history || []).map(h => `
            <div style="display:flex;align-items:center;gap:6px;font-size:0.65rem;color:#555;margin-bottom:2px;">
                <span style="color:${statusColor(h.status)};font-size:0.6rem;">●</span>
                <b style="color:${statusColor(h.status)}">${h.status}</b>
                <span>· ${h.by}</span>
                <span style="color:#333;">${new Date(h.time).toLocaleString()}</span>
            </div>
        `).join('');

        // Build public comments thread
        const comments = data.comments || [];
        const commentsHtml = comments.length === 0 ? '' : `
            <div style="margin-top:8px;border-top:1px solid #1a1a1a;padding-top:6px;">
                <div class="mono" style="font-size:0.6rem;color:#333;margin-bottom:4px;letter-spacing:1px;">AUTHORITY REPLIES</div>
                ${comments.map(c => `
                    <div style="padding:5px 8px;margin-bottom:4px;background:#0a1e12;border-left:2px solid #00ff9d;font-size:0.7rem;font-family:monospace;">
                        <div style="font-size:0.6rem;color:#444;margin-bottom:2px;">${c.author} · ${new Date(c.time).toLocaleTimeString()}</div>
                        ${c.message}
                    </div>
                `).join('')}
            </div>
        `;

        el.innerHTML = `
            <div style="margin-top:8px;padding:10px 12px;background:#111;border:1px solid #222;border-radius:2px;">
                <div class="mono" style="font-size:0.72rem;line-height:2;">
                    Status: <b style="color:${sc};">${data.status}</b><br>
                    Severity: <b style="color:${sev};">${data.severity}</b><br>
                    Dept: <b style="color:#aaa;">${data.department}</b>
                    ${data.input_method === "voice" ? `<br>Method: <b style="color:#00ff9d;">🎙 VOICE (${data.original_language || 'Voice'})</b>` : ''}
                    ${data.resolved_at ? `<br><span style="color:#00ff9d;font-size:0.68rem;">✓ Resolved ${new Date(data.resolved_at).toLocaleString()}</span>` : ''}
                </div>
                ${data.original_transcript ? `
                    <div style="margin-top:6px;padding:6px 8px;background:#141b17;border-left:2px solid #00ff9d;font-size:0.7rem;color:#88b598;">
                        <b>Original Hindi Transcript:</b> "${data.original_transcript}"
                    </div>
                ` : ''}
                ${historyHtml ? `<div style="margin-top:8px;border-top:1px solid #1a1a1a;padding-top:6px;">${historyHtml}</div>` : ''}
                ${commentsHtml}
            </div>
        `;
    } catch (err) {
        el.innerHTML = '<span class="mono" style="font-size:0.7rem;color:#ff4d00;">Could not fetch status.</span>';
    }
};

// Init on load
window.addEventListener("DOMContentLoaded", () => {
    renderTrackingPanel();
});