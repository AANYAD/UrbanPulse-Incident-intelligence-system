import { classifyIncident, translateText } from "./api.js";

// Voice Input & Translation State
window.hasUsedVoiceInput = false;
window.lastVoiceLanguage = null;
let speechRecognizer = null;
let isListening = false;
let isTranslating = false;
let isSubmitting = false;
let lastTranslatedHindi = "";
let isTranslationOutdated = false;

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

window.translateHindiToEnglish = async function(customText = null, isAuto = false) {
    if (isTranslating) return;

    const hindiInput = document.getElementById("hindiTranscript");
    const descInput = document.getElementById("desc");
    const translateBtn = document.getElementById("translateHindiBtn");
    const translateBtnText = document.getElementById("translateBtnText");
    const translationSpinner = document.getElementById("translationSpinner");
    const translationStatus = document.getElementById("translationStatus");
    const descTranslationBadge = document.getElementById("descTranslationBadge");

    const text = (customText !== null && typeof customText === "string")
        ? customText.trim()
        : (hindiInput ? hindiInput.value.trim() : "");

    if (!text) {
        if (!isAuto) {
            if (translationStatus) {
                translationStatus.style.display = "block";
                translationStatus.style.color = "#ff4d00";
                translationStatus.innerText = "Hindi transcript is empty. Please speak or type in Hindi first.";
            }
            alert("Hindi transcript is empty. Please speak or type your complaint in Hindi first.");
        }
        return;
    }

    try {
        isTranslating = true;
        if (translateBtn) {
            translateBtn.disabled = true;
            translateBtn.style.opacity = "0.7";
        }
        if (translateBtnText) translateBtnText.innerText = "TRANSLATING...";
        if (translationSpinner) translationSpinner.style.display = "inline-block";
        if (translationStatus) {
            translationStatus.style.display = "block";
            translationStatus.style.color = "#00ff9d";
            translationStatus.innerText = "Translating Hindi to English via AI4Bharat IndicTrans2...";
        }
        if (descTranslationBadge) {
            descTranslationBadge.style.display = "inline-block";
            descTranslationBadge.innerText = "TRANSLATING...";
            descTranslationBadge.style.color = "#ffcc00";
            descTranslationBadge.style.borderColor = "#ffcc00";
        }

        const data = await translateText(text, "hi-IN");
        const translatedText = data && data.translated_text ? data.translated_text.trim() : "";

        if (!translatedText) {
            throw new Error("Received an empty translation from server.");
        }

        // Display translated English text in the existing English description field (desc)
        if (descInput) {
            descInput.value = translatedText;
            descInput.focus();
        }

        lastTranslatedHindi = text;
        isTranslationOutdated = false;

        if (translationStatus) {
            translationStatus.style.display = "block";
            translationStatus.style.color = "#00ff9d";
            translationStatus.innerHTML = "✓ English translation generated using IndicTrans2. Please review or edit the description below.";
        }
        if (descTranslationBadge) {
            descTranslationBadge.style.display = "inline-block";
            descTranslationBadge.innerText = "AI TRANSLATED — PLEASE REVIEW";
            descTranslationBadge.style.color = "#00ff9d";
            descTranslationBadge.style.borderColor = "#1f3d2b";
        }
        if (translateBtnText) {
            translateBtnText.innerText = "RE-TRANSLATE TO ENGLISH";
        }
    } catch (err) {
        console.error("Translation error:", err);
        isTranslationOutdated = true;
        if (translationStatus) {
            translationStatus.style.display = "block";
            translationStatus.style.color = "#ff4d00";
            translationStatus.innerHTML = `⚠️ Translation failed: ${err.message || "Translation service temporarily unavailable"}. Please retry or enter the English description manually.`;
        }
        if (descTranslationBadge) {
            descTranslationBadge.style.display = "inline-block";
            descTranslationBadge.innerText = "TRANSLATION FAILED";
            descTranslationBadge.style.color = "#ff4d00";
            descTranslationBadge.style.borderColor = "#ff4d00";
        }
        if (translateBtnText) {
            translateBtnText.innerText = "RETRY TRANSLATION";
        }
    } finally {
        isTranslating = false;
        const currentBtn = translateBtn || document.getElementById("translateHindiBtn");
        if (currentBtn) {
            currentBtn.disabled = false;
            currentBtn.style.opacity = "1";
        }
        const currentSpinner = translationSpinner || document.getElementById("translationSpinner");
        if (currentSpinner) {
            currentSpinner.style.display = "none";
        }
    }
};

window.triggerHindiTranslation = function() {
    window.translateHindiToEnglish();
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

            const isHindi = targetLang === "hi-IN" || /[\u0900-\u097F]/.test(transcript);

            window.hasUsedVoiceInput = true;
            window.lastVoiceLanguage = isHindi ? "hi-IN" : targetLang;

            if (isHindi) {
                const hindiContainer = document.getElementById("hindiTranscriptContainer");
                const hindiInput = document.getElementById("hindiTranscript");

                if (hindiContainer) hindiContainer.style.display = "block";
                if (hindiInput) hindiInput.value = transcript;

                if (voiceBadge) {
                    voiceBadge.innerText = "HINDI CAPTURED ✓";
                    voiceBadge.style.color = "#00ff9d";
                    voiceBadge.style.background = "#0c2818";
                    voiceBadge.style.border = "1px solid #00ff9d";
                }

                // Automatically translate captured Hindi transcript into English
                window.translateHindiToEnglish(transcript, true);
            } else {
                // English direct input
                const descInput = document.getElementById("desc");
                const hindiContainer = document.getElementById("hindiTranscriptContainer");
                const hindiInput = document.getElementById("hindiTranscript");
                const descTranslationBadge = document.getElementById("descTranslationBadge");
                const translationStatus = document.getElementById("translationStatus");

                if (hindiContainer) hindiContainer.style.display = "none";
                if (hindiInput) hindiInput.value = "";
                lastTranslatedHindi = "";
                isTranslationOutdated = false;
                if (descTranslationBadge) descTranslationBadge.style.display = "none";
                if (translationStatus) translationStatus.style.display = "none";

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

function setupTranscriptListeners() {
    const hindiInput = document.getElementById("hindiTranscript");
    if (hindiInput) {
        hindiInput.addEventListener("input", () => {
            const currentHindi = hindiInput.value.trim();
            const translateBtnText = document.getElementById("translateBtnText");
            const translationStatus = document.getElementById("translationStatus");
            const descTranslationBadge = document.getElementById("descTranslationBadge");

            if (lastTranslatedHindi && currentHindi !== lastTranslatedHindi) {
                isTranslationOutdated = true;
                if (translationStatus) {
                    translationStatus.style.display = "block";
                    translationStatus.style.color = "#ffcc00";
                    translationStatus.innerText = "⚠️ Hindi transcript was edited. Please click 'Re-Translate to English' before submitting.";
                }
                if (translateBtnText) {
                    translateBtnText.innerText = "RE-TRANSLATE TO ENGLISH";
                }
                if (descTranslationBadge) {
                    descTranslationBadge.style.display = "inline-block";
                    descTranslationBadge.innerText = "TRANSLATION OUTDATED — RE-TRANSLATE";
                    descTranslationBadge.style.color = "#ffcc00";
                    descTranslationBadge.style.borderColor = "#ffcc00";
                }
            } else if (lastTranslatedHindi && currentHindi === lastTranslatedHindi) {
                isTranslationOutdated = false;
                if (translationStatus) {
                    translationStatus.style.display = "block";
                    translationStatus.style.color = "#00ff9d";
                    translationStatus.innerText = "✓ English translation matches current Hindi transcript. Please review below.";
                }
                if (translateBtnText) {
                    translateBtnText.innerText = "RE-TRANSLATE TO ENGLISH";
                }
                if (descTranslationBadge) {
                    descTranslationBadge.style.display = "inline-block";
                    descTranslationBadge.innerText = "AI TRANSLATED — PLEASE REVIEW";
                    descTranslationBadge.style.color = "#00ff9d";
                    descTranslationBadge.style.borderColor = "#1f3d2b";
                }
            }
        });
    }

    const descInput = document.getElementById("desc");
    if (descInput) {
        descInput.addEventListener("input", () => {
            const descTranslationBadge = document.getElementById("descTranslationBadge");
            if (descTranslationBadge && descTranslationBadge.style.display !== "none") {
                if (!isTranslationOutdated) {
                    descTranslationBadge.innerText = "ENGLISH DESCRIPTION (CITIZEN REVIEWED)";
                    descTranslationBadge.style.color = "#00ff9d";
                    descTranslationBadge.style.borderColor = "#1f3d2b";
                }
            }
        });
    }
}

window.handleReport = async function (e) {
    e.preventDefault();

    if (isSubmitting) return;

    if (isTranslating) {
        alert("Translation is currently in progress. Please wait a moment before submitting.");
        return;
    }

    const desc           = document.getElementById("desc").value.trim();
    const category       = document.getElementById("incidentType").value;
    const hindiInput     = document.getElementById("hindiTranscript");
    const originalTranscript = (hindiInput && hindiInput.value.trim()) ? hindiInput.value.trim() : null;

    // Dual-channel validation:
    // If citizen used Hindi voice or entered a Hindi transcript, an English description is required
    // so DistilBERT can classify severity and route accurately without translation errors
    if (originalTranscript) {
        if (!desc) {
            alert("Please provide the English Complaint Description below. You can click 'TRANSLATE TO ENGLISH' or enter it manually. This is required for AI severity assessment and department routing.");
            document.getElementById("desc").focus();
            return;
        }

        // Do not silently submit the original Hindi transcript as the English description
        if (desc === originalTranscript) {
            alert("The English description matches the Hindi transcript. Please click 'TRANSLATE TO ENGLISH' or provide an English translation before submitting.");
            document.getElementById("desc").focus();
            return;
        }

        // If the citizen edited the Hindi transcript after translation, confirm re-translation
        if (isTranslationOutdated) {
            const shouldRetranslate = confirm("The Hindi transcript was modified after translation. Would you like to re-translate to English now before submitting?\n\nClick 'OK' to re-translate now, or 'Cancel' to proceed with the current English description.");
            if (shouldRetranslate) {
                await window.translateHindiToEnglish(originalTranscript);
                return;
            }
        }
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

    const btn     = document.getElementById("submitBtn");
    const btnText = document.getElementById("btnText");

    try {
        isSubmitting = true;
        if (btn) btn.disabled = true;
        if (btnText) btnText.innerText          = "TRANSMITTING...";
        if (btn) {
            btn.style.backgroundColor  = "#ff4d00";
            btn.style.color            = "white";
        }

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

        if (btnText) btnText.innerText = "SENT ✓";
        if (btn) {
            btn.style.backgroundColor = "#00ff9d";
            btn.style.color           = "black";
        }

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
            lastTranslatedHindi = "";
            isTranslationOutdated = false;
            window.hasUsedVoiceInput = false;
            window.lastVoiceLanguage = null;

            const descTranslationBadge = document.getElementById("descTranslationBadge");
            if (descTranslationBadge) descTranslationBadge.style.display = "none";
            const translationStatus = document.getElementById("translationStatus");
            if (translationStatus) translationStatus.style.display = "none";
            const translateBtnText = document.getElementById("translateBtnText");
            if (translateBtnText) translateBtnText.innerText = "TRANSLATE TO ENGLISH";

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
            if (btnText) btnText.innerText        = "Transmit Data";
            if (btn) {
                btn.style.backgroundColor         = "white";
                btn.style.color                   = "black";
                btn.disabled                      = false;
            }
            isSubmitting = false;

            renderTrackingPanel();
        }, 800);

    } catch (err) {
        console.error("Submission error:", err);
        if (btnText) btnText.innerText             = "Transmit Data";
        if (btn) {
            btn.style.backgroundColor              = "white";
            btn.style.color                        = "black";
            btn.disabled                           = false;
        }
        isSubmitting = false;
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

// Check status is managed by index.html with toggle, click-outside, and ESC handling.
if (!window.checkStatus) {
    window.checkStatus = function(refId, event) {
        if (window.toggleCheckStatus) {
            return window.toggleCheckStatus(refId, event);
        }
    };
}

// Init on load
window.addEventListener("DOMContentLoaded", () => {
    setupTranscriptListeners();
    renderTrackingPanel();
});
