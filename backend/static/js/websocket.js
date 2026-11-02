// static/js/websocket.js

export function initWebSocket(url, onMessageCallback) {
    let ws = new WebSocket(url);

    ws.onopen = () => {
        console.log("Connexion WebSocket établie.");
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (onMessageCallback) onMessageCallback(data);
        } catch (e) {
            console.error("Erreur de parsing du message WebSocket :", e);
        }
    };

    ws.onerror = (error) => {
        console.error("Erreur WebSocket :", error);
    };

    ws.onclose = () => {
        console.warn("Connexion WebSocket fermée. Tentative de reconnexion dans 5s...");
        setTimeout(() => {
            // Réassigne la nouvelle instance pour maintenir la connexion active
            ws = initWebSocket(url, onMessageCallback);
        }, 5000);
    };

    return ws;
}
