// static/js/audio.js

export function playTextToSpeech(text) {
    if (!('speechSynthesis' in window)) {
        console.warn("La synthèse vocale n'est pas supportée par ce navigateur.");
        return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'fr-FR';
    window.speechSynthesis.speak(utterance);
}

export function initSpeechRecognition(onResultCallback) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.warn("La reconnaissance vocale n'est pas supportée.");
        return null;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'fr-FR';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        if (onResultCallback) onResultCallback(transcript);
    };

    return recognition;
}

export async function initLiveAudioStream(socket) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

        mediaRecorder.ondataavailable = async (event) => {
            if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
                const reader = new FileReader();
                reader.readAsDataURL(event.data);
                reader.onloadend = () => {
                    const base64Audio = reader.result.split(',')[1];
                    socket.send(JSON.stringify({
                        action: "audio_stream",
                        model: "gemini-3.6-flash", // Utilisation forcée de Gemini Flash 3.6
                        audio: base64Audio
                    }));
                };
            }
        };

        mediaRecorder.start(250);
        console.log("Flux audio Live démarré avec Gemini Flash 3.6.");
        return mediaRecorder;
    } catch (error) {
        console.error("Erreur d'accès au microphone :", error);
    }
}

export function playAudioChunk(base64Data) {
    try {
        const binaryString = atob(base64Data);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'audio/webm' });
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play().catch(e => console.log("Lecture audio ignorée :", e));
    } catch (e) {
        console.error("Erreur de lecture du chunk audio :", e);
    }
}
