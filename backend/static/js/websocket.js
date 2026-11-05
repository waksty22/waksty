// static/js/websocket.js
'use strict';

export function initWebSocket(url, onMessageCallback, onStateCallback) {
    let ws = null;
    let isConnecting = false;
    let shouldReconnect = true;

    async function connect() {
        if (isConnecting || !shouldReconnect) return;
        isConnecting = true;

        try {
            const targetUrl = typeof url === 'function' ? await url() : url;
            if (!shouldReconnect) {
                isConnecting = false;
                return;
            }
            ws = new WebSocket(targetUrl);
        } catch (error) {
            isConnecting = false;
            shouldReconnect = false;
            console.error("Impossible d'obtenir un ticket WebSocket :", error);
            if (onStateCallback) onStateCallback("error", error);
            return;
        }

        ws.onopen = () => {
            isConnecting = false;
            console.log("Connexion WebSocket établie.");
            if (onStateCallback) onStateCallback("open");
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

        ws.onclose = (event) => {
            isConnecting = false;
            if (onStateCallback) onStateCallback("close", event);
            // Si la fermeture est due à une violation de politique (token invalide, ex: 1008), on stoppe les essais
            if (event.code === 1008) {
                console.error("Connexion WebSocket refusée : Jeton invalide ou manquant.");
                shouldReconnect = false;
                return;
            }
            if (shouldReconnect) {
                console.warn("Connexion WebSocket fermée. Tentative de reconnexion dans 5s...");
                setTimeout(() => {
                    connect();
                }, 5000);
            } else {
                console.log("Connexion WebSocket fermée volontairement.");
            }
        };
    }

    connect();

    return {
        send(data) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(typeof data === 'string' ? data : JSON.stringify(data));
            } else {
                console.warn("Impossible d'envoyer : le WebSocket n'est pas ouvert.");
            }
        },
        close() {
            shouldReconnect = false;
            if (ws) {
                ws.close();
            }
        },
        get readyState() {
            return ws ? ws.readyState : WebSocket.CLOSED;
        }
    };
}
