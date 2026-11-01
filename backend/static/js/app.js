// static/js/app.js
import { apiCall } from './api.js';
import { initWebSocket } from './websocket.js';
import { playTextToSpeech, initSpeechRecognition } from './audio.js';

document.addEventListener("DOMContentLoaded", () => {
    console.log("Initialisation de l'application Chappie...");

    // Exemple d'initialisation WebSocket (adaptez l'URL selon votre configuration)
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
    
    initWebSocket(wsUrl, (data) => {
        console.log("Message reçu du serveur :", data);
    });

    // Liaison des événements UI si nécessaire
    const micButton = document.getElementById("mic-button");
    if (micButton) {
        const recognition = initSpeechRecognition((text) => {
            console.log("Texte reconnu :", text);
        });

        micButton.addEventListener("click", () => {
            if (recognition) recognition.start();
        });
    }
});
