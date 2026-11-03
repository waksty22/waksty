// static/js/app.js
'use strict';

import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk } from './audio.js';
import { apiCall } from './api.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application modulaire Chappie V19.4...");

    function getToken() {
        const desktop = document.getElementById("token");
        const mobile = document.getElementById("tokenMobile");
        const memory = document.getElementById("tokenMemory");
        return desktop?.value?.trim() || mobile?.value?.trim() || memory?.value?.trim() || window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";
    }

    const token = getToken();

    // Initialisation WebSocket pour le mode Gemini Live
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
    
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
            return;
        }

        if (liveStatus) liveStatus.textContent = "Connexion au flux Live en cours...";

        liveSocket = initWebSocket(wsUrl, (data) => {
            console.log("Message Live reçu :", data);

            if (data.status && liveStatus) {
                liveStatus.textContent = data.status;
            }

            if (data.type === "audio_stream" || data.audio) {
                if (data.text) {
                    const transcript = document.getElementById("liveTranscript");
                    if (transcript) {
                        transcript.textContent += "\nChappie : " + data.text;
                        transcript.scrollTop = transcript.scrollHeight;
                    }
                }
                if (data.audio) {
                    playAudioChunk(data.audio, data.sample_rate || 24000);
                }
            }
        });

        // Démarrage de l'enregistrement micro pour le Live
        liveRecorder = await initLiveAudioStream(liveSocket);
        if (liveRecorder && liveBtn) {
            liveBtn.textContent = "⏹ Arrêter la conversation live";
            if (liveStatus) liveStatus.textContent = "Mode Live actif. Parle à Chappie.";
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
        console.log("Conversation live arrêtée.");
    };

    // Gestion du bouton de dictée vocale simple
    const micBtn = document.getElementById("micBtn");
    if (micBtn) {
        const recognition = initSpeechRecognition((text) => {
            const msgInput = document.getElementById("msg");
            if (msgInput) {
                msgInput.value = text;
            }
        });

        micBtn.addEventListener("click", () => {
            if (recognition) {
                try {
                    recognition.start();
                    if (liveStatus) liveStatus.textContent = "Écoute en cours...";
                } catch (e) {
                    console.warn("Reconnaissance déjà active ou bloquée", e);
                }
            }
        });
    }

    // Gestion de l'envoi de message texte classique
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
                // Lecture audio optionnelle de la réponse
                playTextToSpeech(data.reply);
            }
        } catch (error) {
            if (outDiv) outDiv.textContent = "Erreur : " + error.message;
        }
    };
});
