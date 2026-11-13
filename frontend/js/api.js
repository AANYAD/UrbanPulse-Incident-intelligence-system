const API_BASE = "http://127.0.0.1:8000";

export async function classifyIncident(description, category, latitude, longitude, imageBase64 = null, originalTranscript = null, originalLanguage = null, inputMethod = "manual") {
    const token = localStorage.getItem('up_token') || null;
    const res = await fetch(`${API_BASE}/classify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            description,
            category,
            latitude,
            longitude,
            image: imageBase64 || null,
            token,   // citizen token so backend can link email for alerts
            original_transcript: originalTranscript || null,
            original_language: originalLanguage || null,
            input_method: inputMethod || "manual"
        })
    });

    if (!res.ok) {
        const err = await res.json();
        throw new Error(JSON.stringify(err.detail));
    }

    return await res.json();
}

export async function fetchIncidents() {
    const res = await fetch(`${API_BASE}/incidents`);
    return await res.json();
}

export async function flagIncidentForReview(incidentId, token) {
    const userToken = token || localStorage.getItem('up_token');
    const res = await fetch(`${API_BASE}/incidents/${incidentId}/flag-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: userToken })
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to flag incident for review");
    }
    return await res.json();
}

export async function adminReviewIncident(incidentId, action, token) {
    const adminToken = token || sessionStorage.getItem('admin_token');
    const res = await fetch(`${API_BASE}/admin/incidents/${incidentId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: adminToken, action })
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Failed to ${action} review request`);
    }
    return await res.json();
}

export async function fetchRemovalRequests(token) {
    const adminToken = token || sessionStorage.getItem('admin_token');
    const res = await fetch(`${API_BASE}/admin/removal-requests?token=${encodeURIComponent(adminToken)}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to fetch removal requests");
    }
    return await res.json();
}