// static/js/websocket.js
'use strict';

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const RECONNECT_JITTER = 0.2;

export function initWebSocket(url, onMessageCallback, onStateCallback) {
    let ws = null;
    let isConnecting = false;
    let shouldReconnect = true;
    let reconnectTimer = null;
    let reconnectAttempts = 0;

    function stopReconnect() {
        shouldReconnect = false;
        if (reconnectTimer !== null) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    }

    function scheduleReconnect() {
        if (!shouldReconnect || reconnectTimer !== null) return;
        const exponentialDelay = Math.min(
            MAX_RECONNECT_DELAY_MS,
            INITIAL_RECONNECT_DELAY_MS * (2 ** reconnectAttempts)
        );
        reconnectAttempts += 1;
        const jitteredDelay = Math.min(
            MAX_RECONNECT_DELAY_MS,
            Math.round(exponentialDelay * (1 - RECONNECT_JITTER + Math.random() * RECONNECT_JITTER * 2))
        );
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, jitteredDelay);
    }

    async function connect() {
        if (isConnecting || !shouldReconnect) return;
        isConnecting = true;

        try {
            // The URL factory is called for every attempt: one-time tickets are never reused.
            const targetUrl = typeof url === 'function' ? await url() : url;
            if (!shouldReconnect) {
                isConnecting = false;
                return;
            }
            ws = new WebSocket(targetUrl);
        } catch (error) {
            isConnecting = false;
            console.error("Impossible d'obtenir un ticket WebSocket :", error);
            if (onStateCallback) onStateCallback("error", error);

            const status = Number(error?.status);
            // Retry network failures and explicitly transient HTTP responses only.
            // Other 4xx responses indicate a permanent request/configuration problem.
            const retryableStatus = [408, 425, 429].includes(status) || status >= 500;
            const hasHttpStatus = Number.isInteger(status) && status > 0;
            if (hasHttpStatus && !retryableStatus) {
                stopReconnect();
                return;
            }
            scheduleReconnect();
            return;
        }

        ws.onopen = () => {
            isConnecting = false;
            reconnectAttempts = 0;
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
            if (event.code === 1008) {
                console.error("Connexion WebSocket refusée : Jeton invalide ou manquant.");
                stopReconnect();
                return;
            }
            if (shouldReconnect) {
                console.warn("Connexion WebSocket fermée. Reconnexion programmée.");
                scheduleReconnect();
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
            stopReconnect();
            if (ws) ws.close();
        },
        get readyState() {
            return ws ? ws.readyState : WebSocket.CLOSED;
        }
    };
}
