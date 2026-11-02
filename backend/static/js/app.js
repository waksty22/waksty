// static/js/app.js
import { apiCall } from './api.js';
import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition, initLiveAudioStream, playAudioChunk } from './audio.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application Chappie...");

    // Récupération sécurisée du token (depuis les attributs du DOM, localStorage ou injecté)
    const token = window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";

    // Initialisation WebSocket avec le token requis par le serveur
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${token}`;
    
    const socket = initWebSocket(wsUrl, (data) => {
        console.log("Message reçu du serveur :", data);

        // Traitement des réponses vocales ou live du serveur
        if (data.type === "audio_response" && data.audio) {
            playAudioChunk(data.audio);
        }
    });

    // Liaison des événements UI du microphone
    const micButton = document.getElementById("mic-button");
    if (micButton) {
        const recognition = initSpeechRecognition((text) => {
            console.log("Texte reconnu :", text);
            // Envoi du texte ou de l'action audio au serveur via le WebSocket
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: "audio",
                    message: text
                }));
            }
        });

        micButton.addEventListener("click", () => {
            if (recognition) {
                recognition.start();
            } else {
                console.warn("La reconnaissance vocale n'est pas disponible, bascule sur le stream audio live.");
                initLiveAudioStream(socket);
            }
        });
    }
});
