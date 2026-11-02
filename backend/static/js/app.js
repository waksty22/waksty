// static/js/app.js
'use strict';

import { apiCall } from './api.js';
import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk } from './audio.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application Chappie...");

    // Récupération sécurisée du token (depuis les attributs du DOM, localStorage ou input)
    const tokenInput = document.getElementById("token") || document.getElementById("tokenMobile");
    const token = tokenInput?.value || window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";

    // Initialisation WebSocket avec le token requis par le serveur
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
    
    const socket = initWebSocket(wsUrl, (data) => {
        console.log("Message reçu du serveur :", data);

        // Traitement des réponses vocales ou live du serveur
        if (data.type === "audio_stream" || data.audio) {
            if (data.text) {
                console.log("Chappie :", data.text);
            }
            if (data.audio) {
                playAudioChunk(data.audio);
            }
        }
    });

    // Liaison des événements UI du microphone
    const micButton = document.getElementById("mic-button") || document.getElementById("liveBtn");
    let liveRecorder = null;

    if (micButton) {
        const recognition = initSpeechRecognition((text) => {
            console.log("Texte reconnu :", text);
            if (text && socket) {
                socket.send({
                    action: "message",
                    message: text
                });
            }
        });

        micButton.addEventListener("click", async () => {
            if (recognition && !liveRecorder) {
                try {
                    recognition.start();
                } catch (e) {
                    console.log("La reconnaissance vocale est déjà active.");
                }
            } else {
                // Bascule / Gestion du stream audio live
                if (!liveRecorder) {
                    console.log("Démarrage du flux audio live...");
                    liveRecorder = await initLiveAudioStream(socket);
                    micButton.textContent = "⏹ Arrêter Live";
                } else {
                    console.log("Arrêt du flux audio live...");
                    if (liveRecorder && typeof liveRecorder.stop === 'function') {
                        liveRecorder.stop();
                    }
                    liveRecorder = null;
                    micButton.textContent = "▶ Démarrer la conversation live";
                }
            }
        });
    }
});
