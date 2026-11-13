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