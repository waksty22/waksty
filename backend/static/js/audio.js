// static/js/audio.js
'use strict';

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
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, sampleRate: 16000 }, video: false });
        
        // Utilisation d'un AudioContext pour récupérer les données PCM brutes
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioCtx.createMediaStreamSource(stream);
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (e) => {
            // CORRECTION : Utilisation de inputBuffer au lieu de inputData
            const inputData = e.inputBuffer.getChannelData(0);
            
            // Conversion en Int16Array (PCM 16-bit)
            const pcm16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
            }

            // Encodage Base64
            const binary = String.fromCharCode.apply(null, new Uint8Array(pcm16.buffer));
            const base64Audio = btoa(binary);

            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: "audio_chunk",
                    pcm_data: base64Audio
                }));
            }
        };

        source.connect(processor);
        processor.connect(audioCtx.destination);

        console.log("Flux audio Live (PCM) démarré.");
        return {
            stop() {
                processor.disconnect();
                source.disconnect();
                stream.getTracks().forEach(track => track.stop());
                if (audioCtx.state !== 'closed') audioCtx.close();
            }
        };
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
        const blob = new Blob([bytes], { type: 'audio/mp3' });
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play().catch(e => console.log("Lecture audio ignorée :", e));
    } catch (e) {
        console.error("Erreur de lecture du chunk audio :", e);
    }
}
