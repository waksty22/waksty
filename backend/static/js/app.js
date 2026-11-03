// static/js/app.js
'use strict';

import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk } from './audio.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application Chappie...");

    function getToken() {
        const desktop = document.getElementById("token");
        const mobile = document.getElementById("tokenMobile");
        return desktop?.value?.trim() || mobile?.value?.trim() || window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";
    }

    const token = getToken();

    // Initialisation WebSocket avec le token requis par le serveur
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
    
    const socket = initWebSocket(wsUrl, (data) => {
        console.log("Message reçu du serveur :", data);

        // Traitement des réponses vocales ou live du serveur
        if (data.type === "connected") {
            console.log(data.message);
        }

        if (data.type === "chat" && data.data) {
            console.log("Chappie (Chat) :", data.data.reply);
        }

        if (data.type === "audio_stream" || data.audio) {
            if (data.text) {
                console.log("Chappie (Audio) :", data.text);
            }
            if (data.audio) {
                playAudioChunk(data.audio);
            }
        }
    });

    // Liaison des événements UI du microphone / Live
    const micButton = document.getElementById("mic-button") || document.getElementById("liveBtn");
    let liveRecorder = null;

    if (micButton) {
        const recognition = initSpeechRecognition((text) => {
            console.log("Texte reconnu :", text);
            if (text && socket) {
                // CORRECTION : action: "chat" alignée avec server.py
                socket.send({
                    action: "chat",
                    message: text
                });
            }
        });

        micButton.addEventListener("click", async () => {
            // Bascule / Gestion du stream audio live
            if (!liveRecorder) {
                console.log("Démarrage du flux audio live...");
                liveRecorder = await initLiveAudioStream(socket);
                if (liveRecorder) {
                    micButton.textContent = "⏹ Arrêter Live";
                }
            } else {
                console.log("Arrêt du flux audio live...");
                if (liveRecorder && typeof liveRecorder.stop === 'function') {
                    liveRecorder.stop();
                }
                liveRecorder = null;
                micButton.textContent = "▶ Démarrer la conversation live";
            }
        });
    }
});
