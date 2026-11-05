'use strict';

import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk, interruptAudioPlayback } from './audio.js';
import { apiCall } from './api.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application modulaire Chappie V19.3...");

    // Fonction centralisée et robuste pour récupérer le token de partout
    function getToken() {
        const desktop = document.getElementById("token");
        const mobile = document.getElementById("tokenMobile");
        const memory = document.getElementById("tokenMemory");
        
        const val = desktop?.value?.trim() || mobile?.value?.trim() || memory?.value?.trim() || window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";
        
        if (val) {
            localStorage.setItem("chappie_token", val);
        }
        return val;
    }

    // Synchronisation globale des champs de token (appelée par oninput dans le HTML)
    window.syncTokens = function(source) {
        const tokenVal = getToken();
        ["token", "tokenMobile", "tokenMemory"].forEach(id => {
            const el = document.getElementById(id);
            if (el && el.value !== tokenVal) {
                el.value = tokenVal;
            }
        });
        if (tokenVal) {
            window.CHAPPIE_TOKEN = tokenVal;
        }
    };

    // Pré-remplir les champs si un token est déjà en mémoire
    const savedToken = getToken();
    if (savedToken) {
        ["token", "tokenMobile", "tokenMemory"].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = savedToken;
        });
    }

    // ==========================================
    // EXPOSITION GLOBALE DES FONCTIONS (HTML ONCLICK)
    // ==========================================

    window.fetchPsychology = async function() {
        const token = getToken();
        if (!token) {
            alert("Veuillez saisir votre jeton API.");
            return;
        }
        try {
            const data = await apiCall('/api/emotions', {
                method: 'GET',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (data && data.emotions) {
                const statValues = document.querySelectorAll('.stat-card .stat-value');
                if (statValues.length >= 3) {
                    statValues[0].textContent = Math.round(data.emotions.energy ?? 0) + '%';
                    statValues[1].textContent = Math.round(data.emotions.joy ?? 0) + '%';
                    statValues[2].textContent = Math.round(data.emotions.curiosity ?? 0) + '%';
                }
            }
            const statusEl = document.getElementById('status');
            if (statusEl) statusEl.textContent = "États généraux actualisés.";
        } catch (error) {
            console.error("Erreur fetchPsychology :", error);
            const statusEl = document.getElementById('status');
            if (statusEl) statusEl.textContent = "Erreur de mise à jour des états.";
        }
    };

    window.loadVocabulary = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/language/vocabulary', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const output = document.getElementById('vocabularyOutput');
            if (output) output.textContent = (data.vocabulary || []).map(item =>
                item.word + ' — ' + item.state + (item.meaning ? ' : ' + item.meaning : '')
            ).join('\n') || 'Aucun mot appris pour le moment.';
        } catch (error) {
            const output = document.getElementById('vocabularyOutput');
            if (output) output.textContent = 'Erreur : ' + error.message;
        }
    };

    window.teachVocabulary = async function() {
        const word = document.getElementById('teachWord')?.value?.trim();
        const state = document.getElementById('teachState')?.value || 'heard';
        const meaning = document.getElementById('teachMeaning')?.value?.trim() || '';
        const token = getToken();
        if (!word) return alert('Saisis un mot à enseigner.');
        try {
            await apiCall('/api/language/teach', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token },
                body: { user_id: 'creator', word, state, meaning,
                    evidence: 'Enseignement validé depuis le tableau de bord' }
            });
            await window.loadVocabulary();
        } catch (error) { alert(error.message); }
    };

    window.associateVisionWord = async function() {
        const word = document.getElementById("visionWord")?.value?.trim();
        const observationId = document.getElementById("visionObservationId")?.value?.trim();
        const token = getToken();
        if (!word || !observationId) {
            alert("Analyse d'abord une image et enseigne le mot à associer.");
            return;
        }
        try {
            const result = await apiCall("/api/vision/associate", {
                method: "POST",
                headers: { "Authorization": "Bearer " + token },
                body: {
                    word: word,
                    observation_id: observationId,
                    evidence: "Association image-mot validée manuellement par le créateur"
                }
            });
            const status = document.getElementById("visionObservationStatus");
            if (status) status.textContent =
                "Association enregistrée : " + result.association.word
                + " ↔ observation visuelle. Le mot n'est pas automatiquement compris.";
        } catch (error) {
            alert(error.message);
        }
    };

    window.loadSensoryObservations = async function() {
        const token = getToken();
        try {
            const data = await apiCall("/api/senses/observations", {
                headers: { "Authorization": "Bearer " + token }
            });
            const output = document.getElementById("sensoryHistory");
            if (output) output.textContent = (data.observations || []).map(item =>
                "[" + item.modality + "] " + item.content
            ).join("\n\n") || "Aucune expérience sensorielle enregistrée.";
        } catch (error) {
            const output = document.getElementById("sensoryHistory");
            if (output) output.textContent = "Erreur : " + error.message;
        }
    };

    window.loadKnownObjects = async function() {
        const token = getToken();
        const output = document.getElementById("knownObjectsOutput");
        try {
            const data = await apiCall("/api/learning/objects", {
                headers: { "Authorization": "Bearer " + token }
            });
            const objects = data.objects || [];
            if (output) output.textContent = objects.length
                ? objects.map(object => {
                    const props = (object.properties || []).map(p =>
                        "  • " + p.property_key + " : " + p.property_value
                        + " [" + p.source_type + ", confiance "
                        + Math.round(p.confidence * 100) + "%]"
                    ).join("\\n");
                    const experiences = (object.experiences || []).map(e =>
                        "  ↳ " + e.action + " → " + e.outcome
                    ).join("\\n");
                    return object.word + " (" + object.vocabulary_state + ")\\n"
                        + (props || "  Aucune propriété apprise.") + "\\n"
                        + (experiences || "  Aucune expérience enregistrée.");
                }).join("\\n\\n")
                : "Aucun objet reconnu pour le moment.";
        } catch (error) {
            if (output) output.textContent = "Erreur : " + error.message;
        }
    };

    window.teachObjectProperty = async function() {
        const word = document.getElementById("objectWord")?.value?.trim();
        const property = document.getElementById("objectProperty")?.value;
        const value = document.getElementById("objectValue")?.value?.trim();
        const evidence = document.getElementById("objectEvidence")?.value?.trim() || "";
        const status = document.getElementById("objectLearningStatus");
        if (!word || !value) return alert("Indique un objet et une valeur.");
        try {
            const result = await apiCall("/api/learning/object-property", {
                method: "POST",
                headers: { "Authorization": "Bearer " + getToken() },
                body: { word, property, value, evidence, confidence: 0.9 }
            });
            if (status) status.textContent = "Appris : " + result.property.word
                + " — " + result.property.property_key + " : "
                + result.property.property_value;
            await window.loadKnownObjects();
        } catch (error) {
            if (status) status.textContent = "Non enregistré : " + error.message;
        }
    };

    window.recordObjectExperience = async function() {
        const word = document.getElementById("experienceWord")?.value?.trim();
        const action = document.getElementById("experienceAction")?.value?.trim();
        const outcome = document.getElementById("experienceOutcome")?.value?.trim();
        const status = document.getElementById("objectExperienceStatus");
        if (!word || !action || !outcome) {
            return alert("Renseigne l'objet, l'action et le résultat observé.");
        }
        try {
            const result = await apiCall("/api/learning/object-experience", {
                method: "POST",
                headers: { "Authorization": "Bearer " + getToken() },
                body: { word, action, outcome, confidence: 0.6 }
            });
            if (status) status.textContent = "Expérience mémorisée pour "
                + result.experience.word + ". Elle n'est pas encore une règle générale.";
            await window.loadKnownObjects();
        } catch (error) {
            if (status) status.textContent = "Non enregistrée : " + error.message;
        }
    };

    window.compareKnownObjects = async function() {
        const first = document.getElementById("compareObjectA")?.value?.trim();
        const second = document.getElementById("compareObjectB")?.value?.trim();
        const output = document.getElementById("objectComparisonOutput");
        if (!first || !second) return alert("Indique deux objets à comparer.");
        try {
            const data = await apiCall("/api/learning/object-compare", {
                method: "POST",
                headers: { "Authorization": "Bearer " + getToken() },
                body: { first, second }
            });
            const comparison = data.comparison;
            const shared = Object.entries(comparison.shared_properties || {})
                .map(([key, values]) => key + " : " + values.join(", "));
            const differences = Object.entries(comparison.differences || {})
                .map(([key, values]) => key + " — " + first + " : "
                    + (values[first].join(", ") || "inconnu")
                    + " / " + second + " : "
                    + (values[second].join(", ") || "inconnu"));
            if (output) output.textContent =
                "Points communs\\n" + (shared.join("\\n") || "Aucun connu")
                + "\\n\\nDifférences connues\\n"
                + (differences.join("\\n") || "Aucune différence enregistrée")
                + "\\n\\n" + comparison.warning;
        } catch (error) {
            if (output) output.textContent = "Comparaison impossible : " + error.message;
        }
    };

    window.loadSkills = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/skills', { headers: { 'Authorization': `Bearer ${token}` } });
            const summaryEl = document.getElementById('summary');
            if (summaryEl) {
                summaryEl.textContent = JSON.stringify(data, null, 2);
            }
        } catch (e) { console.error(e); }
    };

    window.loadGoals = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/goals', { headers: { 'Authorization': `Bearer ${token}` } });
            const memoryOutput = document.getElementById('memoryOutput');
            if (memoryOutput) {
                memoryOutput.textContent = JSON.stringify(data, null, 2);
            }
        } catch (e) { console.error(e); }
    };

    window.loadSummary = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/memory/summary', { headers: { 'Authorization': `Bearer ${token}` } });
            const memoryOutput = document.getElementById('memoryOutput');
            if (memoryOutput) {
                memoryOutput.textContent = data.summary || "Aucun résumé disponible.";
            }
        } catch (e) { console.error(e); }
    };

    window.loadDreams = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/dreams', { headers: { 'Authorization': `Bearer ${token}` } });
            const memoryOutput = document.getElementById('memoryOutput');
            if (memoryOutput) {
                memoryOutput.textContent = JSON.stringify(data, null, 2);
            }
        } catch (e) { console.error(e); }
    };

    window.loadThoughts = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/thoughts', { headers: { 'Authorization': `Bearer ${token}` } });
            const memoryOutput = document.getElementById('memoryOutput');
            if (memoryOutput) {
                memoryOutput.textContent = JSON.stringify(data, null, 2);
            }
        } catch (e) { console.error(e); }
    };

    window.loadMoodHistory = async function() {
        const token = getToken();
        try {
            const data = await apiCall('/api/mood/history', { headers: { 'Authorization': `Bearer ${token}` } });
            const memoryOutput = document.getElementById('memoryOutput');
            if (memoryOutput) {
                memoryOutput.textContent = JSON.stringify(data, null, 2);
            }
        } catch (e) { console.error(e); }
    };

    window.consolidate = async function() {
        const token = getToken();
        const output = document.getElementById("memoryOutput");
        try {
            const data = await apiCall("/api/memory/consolidate", {
                method: "POST", headers: { "Authorization": "Bearer " + token }
            });
            if (output) output.textContent = JSON.stringify(data.consolidation || data, null, 2);
        } catch (error) {
            if (output) output.textContent = "Erreur de consolidation : " + error.message;
        }
    };

    window.resetLife = async function() {
        if (!confirm("Attention : cela va effacer toute la mémoire de Chappie. Continuer ?")) return;
        const token = getToken();
        try {
            await apiCall('/api/reset', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
            alert("Chappie a été réinitialisé.");
            window.fetchPsychology();
        } catch (e) { alert("Erreur lors de la réinitialisation."); }
    };

    // ==========================================
    // GEMINI LIVE (WEBSOCKET /ws)
    // ==========================================
    let liveSocket = null;
    let liveRecorder = null;
    const liveBtn = document.getElementById("liveBtn");
    const liveStatus = document.getElementById("liveStatus");

    window.toggleLive = async function() {
        if (liveSocket && liveSocket.readyState === WebSocket.OPEN) {
            stopLive();
            return;
        }

        const currentToken = getToken();
        if (!currentToken) {
            if (liveStatus) liveStatus.textContent = "Saisis ton jeton API avant de démarrer.";
            alert("Veuillez saisir votre jeton API (CHAPPIE_API_TOKEN).");
            return;
        }

        if (liveStatus) liveStatus.textContent = "Connexion au flux Live en cours...";

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${encodeURIComponent(currentToken)}`;

        liveSocket = initWebSocket(wsUrl, (data) => {
            console.log("Message Live reçu :", data);

            if (data.message && liveStatus) {
                liveStatus.textContent = data.message;
            }

            if (data.type === "user_text" && typeof data.text === "string") {
                const transcript = document.getElementById("liveTranscript");
                if (transcript) {
                    transcript.textContent += "\nToi : " + data.text;
                    transcript.scrollTop = transcript.scrollHeight;
                }
            }

            if (data.type === "text" && typeof data.text === "string") {
                const transcript = document.getElementById("liveTranscript");
                if (transcript) {
                    transcript.textContent += "\nChappie : " + data.text;
                    transcript.scrollTop = transcript.scrollHeight;
                }
                // The transcription accompanies Gemini's native audio. Do not
                // start a second browser TTS voice over the native Live voice.
            }

            if (data.type === "audio_stream" && data.audio) {
                playAudioChunk(data.audio, data.sample_rate || 24000);
            }

            if (data.type === "interrupt") {
                interruptAudioPlayback();
                console.info("Gemini Live a interrompu sa réponse audio.");
            }

            if (data.type === "speech_blocked") {
                if (liveStatus) liveStatus.textContent = data.message || "Réponse vocale bloquée par le vocabulaire acquis.";
            }

            if (data.type === "error" || data.error) {
                console.error("Erreur Gemini Live :", data.message || data.error);
                if (liveStatus) liveStatus.textContent = "Erreur Gemini Live : " + (data.message || data.error);
            }
        });

        try {
            liveRecorder = await initLiveAudioStream(liveSocket);
            if (liveRecorder && liveBtn) {
                liveBtn.textContent = "⏹ Arrêter la conversation live";
                if (liveStatus) liveStatus.textContent = "Mode Live actif. Parle à Chappie.";
            }
        } catch (e) {
            console.error("Erreur initialisation micro live :", e);
            if (liveStatus) liveStatus.textContent = "Erreur d'accès au microphone.";
            if (liveSocket) liveSocket.close();
        }
    };

    window.stopLive = function() {
        if (liveRecorder && typeof liveRecorder.stop === 'function') {
            liveRecorder.stop();
        }
        liveRecorder = null;

        if (liveSocket) {
            liveSocket.close();
            liveSocket = null;
        }

        if (liveBtn) {
            liveBtn.textContent = "▶ Démarrer la conversation live";
        }
        if (liveStatus) {
            liveStatus.textContent = "Session Live terminée.";
        }
    };

    // ==========================================
    // CAMÉRA / ANALYSE VISION (CORRIGÉ & AJOUTÉ)
    // ==========================================
    let mediaStream = null;

    window.startCamera = async function() {
        const videoElement = document.getElementById("camera");
        const visionOut = document.getElementById("visionOut");
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: "user" }, 
                audio: false 
            });
            videoElement.srcObject = mediaStream;
            if (visionOut) visionOut.textContent = "Caméra active. Prêt pour l'analyse.";
        } catch (err) {
            console.error("Erreur d'accès à la caméra :", err);
            if (visionOut) visionOut.textContent = "Erreur : Permissions refusées ou caméra indisponible.";
        }
    };

    window.stopCamera = function() {
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
        const videoElement = document.getElementById("camera");
        if (videoElement) videoElement.srcObject = null;
        const visionOut = document.getElementById("visionOut");
        if (visionOut) visionOut.textContent = "Caméra inactive.";
    };

    window.captureVision = async function() {
        const videoElement = document.getElementById("camera");
        const visionOut = document.getElementById("visionOut");
        if (!mediaStream) {
            alert("Veuillez d'abord activer la caméra.");
            return;
        }

        const canvas = document.createElement("canvas");
        canvas.width = videoElement.videoWidth || 640;
        canvas.height = videoElement.videoHeight || 480;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
        const imageBase64 = canvas.toDataURL("image/jpeg", 0.8);

        if (visionOut) visionOut.textContent = "Analyse de l'image par Chappie...";
        
        const token = getToken();
        if (!token) {
            alert("Veuillez saisir votre jeton API.");
            return;
        }

        try {
            const response = await apiCall('/api/vision/analyze', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: {
                    image: imageBase64,
                    question: "Décris ce que tu vois.",
                    ...(locationSessionId && latestLocation ? {
                        session_id: locationSessionId,
                        latitude: latestLocation.latitude,
                        longitude: latestLocation.longitude
                    } : {})
                }
            });
            if (visionOut) {
                visionOut.textContent = response.analysis
                    + "\n\nObservation sensorielle enregistrée. "
                    + "Cette description n'est pas encore un savoir acquis.";
            }
            const observationField = document.getElementById("visionObservationId");
            if (observationField) observationField.value = response.observation_id || "";
            const observationLabel = document.getElementById("visionObservationStatus");
            if (observationLabel) observationLabel.textContent =
                response.observation_id ? "Observation enregistrée — associe maintenant un mot enseigné." : "Observation non enregistrée.";
        } catch (error) {
            console.error("Erreur analyse vision :", error);
            if (visionOut) visionOut.textContent = "Erreur lors de l'analyse visuelle : " + error.message;
        }
    };

    // ==========================================
    // RECONNAISSANCE VOCALE & CHAT STANDARD
    // ==========================================
    const micBtn = document.getElementById("micBtn");
    const recognition = initSpeechRecognition((text) => {
        const msgInput = document.getElementById("msg");
        if (msgInput) {
            msgInput.value = text;
        }
    });

    window.toggleMic = function() {
        if (recognition) {
            try {
                recognition.start();
                if (liveStatus) liveStatus.textContent = "Écoute en cours...";
            } catch (e) {
                console.warn("Reconnaissance déjà active", e);
            }
        }
    };

    if (micBtn) {
        micBtn.addEventListener("click", () => {
            window.toggleMic();
        });
    }

    window.sendMessage = async function() {
        const msgInput = document.getElementById("msg");
        const outDiv = document.getElementById("out");
        if (!msgInput) return;

        const message = msgInput.value.trim();
        if (!message) return;

        if (outDiv) outDiv.textContent = "Chappie réfléchit...";

        try {
            const data = await apiCall('/api/chat', {
                method: 'POST',
                body: { user_id: 'creator', message }
            });

            if (data.reply) {
                if (outDiv) outDiv.textContent = data.reply;
                msgInput.value = "";
                playTextToSpeech(data.reply);
            }
        } catch (error) {
            if (outDiv) outDiv.textContent = "Erreur : " + error.message;
        }
    };


    // V33 — causal learning controls
    window.createCausalObservation = async function() {
        const value = id => document.getElementById(id)?.value?.trim() || "";
        const status = document.getElementById("causalLearningStatus");
        try {
            const result = await apiCall("/api/learning/causal/observations", {
                method: "POST",
                body: { event: value("causalEvent"), context: value("causalContext"),
                    outcome: value("causalOutcome"), source_type: "observed",
                    evidence: "Observation saisie et confirmée par le superviseur.", confidence: 0.7 }
            });
            const field = document.getElementById("causalObservationId");
            if (field && result.observation?.id) field.value = result.observation.id;
            if (status) status.textContent = "Observation enregistrée. Identifiant : " + (result.observation?.id ?? "—");
            await window.loadCausalLearning();
        } catch (error) { if (status) status.textContent = "Erreur : " + error.message; }
    };

    window.createCausalHypothesis = async function() {
        const value = id => document.getElementById(id)?.value?.trim() || "";
        const status = document.getElementById("causalLearningStatus");
        try {
            const result = await apiCall("/api/learning/causal/hypotheses", {
                method: "POST",
                body: { observation_id: Number(value("causalObservationId")),
                    statement: value("causalHypothesis"),
                    predicted_effect: value("causalPrediction"), confidence: 0.3 }
            });
            const field = document.getElementById("causalHypothesisId");
            if (field && result.hypothesis?.id) field.value = result.hypothesis.id;
            if (status) status.textContent = "Hypothèse enregistrée, elle reste à vérifier. ID : " + (result.hypothesis?.id ?? "—");
            await window.loadCausalLearning();
        } catch (error) { if (status) status.textContent = "Erreur : " + error.message; }
    };

    window.createCausalExperiment = async function() {
        const value = id => document.getElementById(id)?.value?.trim() || "";
        const approved = document.getElementById("causalSupervisorApproval")?.checked === true;
        const status = document.getElementById("causalLearningStatus");
        try {
            const result = await apiCall("/api/learning/causal/experiments", {
                method: "POST",
                body: { hypothesis_id: Number(value("causalHypothesisId")),
                    environment: value("causalEnvironment"), procedure: value("causalProcedure"),
                    prediction: value("causalExperimentPrediction"), supervisor_approved: approved }
            });
            const field = document.getElementById("causalExperimentId");
            if (field && result.experiment?.id) field.value = result.experiment.id;
            if (status) status.textContent = "Protocole enregistré. ID : " + (result.experiment?.id ?? "—");
            await window.loadCausalLearning();
        } catch (error) { if (status) status.textContent = "Erreur : " + error.message; }
    };

    window.evaluateCausalExperiment = async function() {
        const value = id => document.getElementById(id)?.value?.trim() || "";
        const status = document.getElementById("causalLearningStatus");
        const id = Number(value("causalExperimentId"));
        try {
            await apiCall("/api/learning/causal/experiments/" + id + "/result", {
                method: "POST",
                body: { observed_result: value("causalObservedResult"), evaluation: value("causalEvaluation") }
            });
            if (status) status.textContent = "Résultat évalué et enregistré.";
            await window.loadCausalLearning();
        } catch (error) { if (status) status.textContent = "Erreur : " + error.message; }
    };

    window.loadCausalLearning = async function() {
        const output = document.getElementById("causalLearningOutput");
        try {
            const data = await apiCall("/api/learning/causal");
            if (output) output.textContent = JSON.stringify(data, null, 2);
        } catch (error) { if (output) output.textContent = "Erreur de chargement : " + error.message; }
    };

    // V33 — consent-based location tracking and spatial memory
    let locationWatchId = null;
    let locationSessionId = null;
    let latestLocation = null;
    let leafletMap = null;
    let spatialLayer = null;
    let samplesSinceRefresh = 0;

    function setLocationStatus(message) {
        const el = document.getElementById("locationStatus");
        if (el) el.textContent = message;
    }

    function renderWorldMap(data) {
        const mapElement = document.getElementById("chappieWorldMap");
        const stats = document.getElementById("worldMapStats");
        const placesList = document.getElementById("worldPlacesList");
        if (stats) {
            const st = data.statistics || {};
            stats.textContent = (st.sessions || 0) + " sessions · " +
                (st.location_samples || 0) + " positions · " +
                (st.known_place_observations || 0) + " observations de lieux";
        }
        if (placesList) {
            placesList.replaceChildren();
            const places = data.places || [];
            if (!places.length) {
                placesList.textContent = "Aucun lieu observé pour le moment.";
            } else {
                places.slice(0, 12).forEach(place => {
                    const item = document.createElement("div");
                    item.className = "info-card";
                    const title = document.createElement("strong");
                    title.textContent = place.label || "Lieu non identifié";
                    const description = document.createElement("p");
                    description.className = "muted";
                    description.textContent = place.description || "Aucune description.";
                    const meta = document.createElement("small");
                    meta.textContent = (place.identity_status || "unconfirmed") + " · " +
                        (place.observations_count || 1) + " observation(s)";
                    item.append(title, description, meta);
                    placesList.appendChild(item);
                });
            }
        }
        if (!mapElement || !window.L) {
            if (mapElement) mapElement.textContent = "La bibliothèque cartographique n'a pas pu être chargée.";
            return;
        }
        if (!leafletMap) {
            leafletMap = window.L.map(mapElement, { scrollWheelZoom: false }).setView([46.6, 2.45], 6);
            window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
            }).addTo(leafletMap);
            spatialLayer = window.L.layerGroup().addTo(leafletMap);
        }
        spatialLayer.clearLayers();
        const visits = data.visits || [];
        const bySession = new Map();
        visits.forEach(point => {
            const coords = [Number(point.latitude), Number(point.longitude)];
            if (!Number.isFinite(coords[0]) || !Number.isFinite(coords[1])) return;
            if (!bySession.has(point.session_id)) bySession.set(point.session_id, []);
            bySession.get(point.session_id).push(coords);
            window.L.circleMarker(coords, { radius: 5, weight: 1, fillOpacity: 0.75 })
                .bindTooltip(new Date(point.recorded_at).toLocaleString("fr-FR"))
                .addTo(spatialLayer);
        });
        bySession.forEach(coords => {
            if (coords.length > 1) window.L.polyline(coords, { weight: 3, opacity: 0.75 }).addTo(spatialLayer);
        });
        (data.places || []).forEach(place => {
            if (place.latitude == null || place.longitude == null) return;
            const popup = document.createElement("div");
            const strong = document.createElement("strong");
            strong.textContent = place.label || "Lieu non identifié";
            const p = document.createElement("p");
            p.textContent = place.description || "";
            popup.append(strong, p);
            window.L.marker([Number(place.latitude), Number(place.longitude)])
                .bindPopup(popup).addTo(spatialLayer);
        });
        const all = visits.map(p => [Number(p.latitude), Number(p.longitude)])
            .filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]));
        if (all.length) leafletMap.fitBounds(window.L.latLngBounds(all), { padding: [24, 24], maxZoom: 15 });
        setTimeout(() => leafletMap.invalidateSize(), 100);
    }

    window.loadWorldMap = async function() {
        try {
            const data = await apiCall("/api/world/map");
            renderWorldMap(data.map || {});
        } catch (error) { setLocationStatus("Impossible de charger la carte : " + error.message); }
    };

    window.startLocationTracking = async function() {
        if (!navigator.geolocation) {
            setLocationStatus("La géolocalisation n'est pas disponible sur ce navigateur.");
            return;
        }
        if (locationWatchId !== null) return;
        try {
            const session = await apiCall("/api/world/location/session", {
                method: "POST", body: { consented: true, device_label: "Navigateur Chappie" }
            });
            locationSessionId = session.session.session_id;
            setLocationStatus("Session autorisée. Demande de position au navigateur…");
            locationWatchId = navigator.geolocation.watchPosition(async position => {
                latestLocation = position.coords;
                try {
                    await apiCall("/api/world/location", {
                        method: "POST",
                        body: {
                            session_id: locationSessionId,
                            latitude: position.coords.latitude, longitude: position.coords.longitude,
                            accuracy_m: position.coords.accuracy, altitude_m: position.coords.altitude,
                            heading_deg: position.coords.heading, speed_mps: position.coords.speed,
                            recorded_at: new Date(position.timestamp).toISOString()
                        }
                    });
                    samplesSinceRefresh += 1;
                    setLocationStatus("Localisation active · précision " +
                        Math.round(position.coords.accuracy) + " m. Arrête le suivi à tout moment.");
                    if (samplesSinceRefresh >= 3) {
                        samplesSinceRefresh = 0;
                        await window.loadWorldMap();
                    }
                } catch (error) { setLocationStatus("Position non enregistrée : " + error.message); }
            }, error => {
                setLocationStatus("Erreur de localisation : " + error.message);
            }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 });
        } catch (error) {
            locationSessionId = null;
            setLocationStatus("Impossible de démarrer la session : " + error.message);
        }
    };

    window.stopLocationTracking = async function() {
        if (locationWatchId !== null) navigator.geolocation.clearWatch(locationWatchId);
        locationWatchId = null;
        const sessionId = locationSessionId;
        locationSessionId = null;
        latestLocation = null;
        if (sessionId) {
            try {
                await apiCall("/api/world/location/session/stop", {
                    method: "POST", body: { session_id: sessionId }
                });
            } catch (error) {
                setLocationStatus("Suivi arrêté localement. Fermeture serveur à vérifier : " + error.message);
                return;
            }
        }
        setLocationStatus("Suivi arrêté. Aucune position n'est collectée en dehors d'une session active.");
        await window.loadWorldMap();
    };

    window.stopSpeech = function() {
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        interruptAudioPlayback();
    };

    window.recordVoice = function() {
        alert("La reconnaissance de profil vocal n'est pas encore implémentée : aucune empreinte biométrique réelle n'est entraînée.");
    };

    // Charger automatiquement les états si un token est déjà enregistré au démarrage
    if (savedToken) {
        window.fetchPsychology();
        window.loadWorldMap();
        window.loadCausalLearning();
    }
});
