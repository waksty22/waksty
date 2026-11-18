// static/js/api.js
'use strict';

export async function apiCall(url, options = {}) {
    const tokenInput = document.getElementById("token") || document.getElementById("tokenMobile") || document.getElementById("tokenMemory");
    const token = tokenInput?.value?.trim() || "";

    const headers = {
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...options.headers
    };

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


export async function apiDownload(url, filename = "download.bin") {
    const tokenInput = document.getElementById("token") ||
        document.getElementById("tokenMobile") ||
        document.getElementById("tokenMemory");
    const token = tokenInput?.value?.trim() ||
        "";
    const headers = token
        ? { "Authorization": `Bearer ${token}` }
        : {};

    const response = await fetch(url, { method: "GET", headers });
    if (!response.ok) {
        const contentType = response.headers.get("content-type") || "";
        let detail = "";
        try {
            detail = contentType.includes("application/json")
                ? JSON.stringify((await response.json()).detail || "Erreur API")
                : await response.text();
        } catch (_) {
            detail = "Erreur HTTP " + response.status;
        }
        throw new Error(detail || ("Erreur HTTP " + response.status));
    }

    const blob = await response.blob();
    if (!blob.size) {
        throw new Error("L'archive reçue est vide.");
    }
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);

    return {
        size_bytes: blob.size,
        verified: response.headers.get("X-Backups-Verified") === "true",
        encrypted: response.headers.get("X-Backups-Encrypted") || "",
        sqlite_sha256: response.headers.get("X-SQLite-Backup-SHA256") || "",
        turso_sha256: response.headers.get("X-Turso-Backup-SHA256") || "",
        sqlite_rows: Number(response.headers.get("X-SQLite-Row-Count") || 0),
        turso_rows: Number(response.headers.get("X-Turso-Row-Count") || 0)
    };
}
