// static/js/api.js
'use strict';

export async function apiCall(url, options = {}) {
    // Récupération dynamique du token depuis l'interface utilisateur
    const tokenInput = document.getElementById("token") || document.getElementById("tokenMobile");
    const token = tokenInput?.value?.trim() || window.CHAPPIE_TOKEN || localStorage.getItem("chappie_token") || "";

    const headers = {
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...options.headers
    };

    // Si le corps n'est ni un Blob, ni un FormData, ni un ArrayBuffer, on s'assure qu'il est en JSON
    const isBinary = options.body instanceof Blob || options.body instanceof FormData || options.body instanceof ArrayBuffer;
    
    if (!isBinary && options.body && typeof options.body === 'object' && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
    }

    try {
        const response = await fetch(url, {
            ...options,
            headers
        });

        const contentType = response.headers.get("content-type") || "";
        let data;

        if (contentType.includes("application/json")) {
            data = await response.json();
        } else {
            data = await response.text();
        }

        if (!response.ok) {
            const errorMsg = typeof data === 'object' ? (data.detail || data.message || data.error) : data;
            throw new Error(errorMsg || `Erreur HTTP ${response.status}: ${response.statusText}`);
        }

        return data;
    } catch (error) {
        console.error("Erreur lors de l'appel API :", error);
        throw error;
    }
}
