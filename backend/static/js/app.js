// static/js/app.js
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
        // Passage du token en paramètre de requête pour correspondre au serveur
        const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${encodeURIComponent(currentToken)}`;

        liveSocket = initWebSocket(wsUrl, (data) => {
            console.log("Message Live reçu :", data);

            if (data.message && liveStatus) {
                liveStatus.textContent = data.message;
            }

            if (data.type === "audio_session" || data.type === "audio_stream" || data.audio) {
                if (data.text) {
                    const transcript = document.getElementById("liveTranscript");
                    if (transcript) {
                        transcript.textContent += "\nChappie : " + data.text;
                        transcript.scrollTop = transcript.scrollHeight;
                    }
                }
                const audioContent = data.audio || data.audio_data;
                if (audioContent) {
                    playAudioChunk(audioContent, data.sample_rate || 24000);
                }
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
    // CAMÉRA / ANALYSE VISION (/api/vision/analyze)
    // ==========================================
    window.analyzeCameraImage = async function(imageBase64, customQuestion = "Décris ce que tu vois.") {
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
                    question: customQuestion
                }
            });

            return response.analysis;
        } catch (error) {
            console.error("Erreur analyse vision :", error);
            throw error;
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
