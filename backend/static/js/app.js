'use strict';

import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk } from './audio.js';
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
        alert("Fonction de consolidation déclenchée.");
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
                if ("speechSynthesis" in window) playTextToSpeech(data.text);
            }
            // Raw Gemini audio is discarded because it cannot be lexically validated.
            if (data.type === "audio_session" || data.type === "audio_stream" || data.audio) {
                console.warn("Audio Live brut ignoré : validation lexicale obligatoire.");
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
                    question: "Décris ce que tu vois."
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

    // Charger automatiquement les états si un token est déjà enregistré au démarrage
    if (savedToken) {
        window.fetchPsychology();
    }
});
