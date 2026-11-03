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
        const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: { 
                channelCount: 1, 
                sampleRate: 16000 
            }, 
            video: false 
        });
        
        // Utilisation d'un AudioContext fixé à 16 000 Hz pour l'entrée micro
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioCtx.createMediaStreamSource(stream);
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (e) => {
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

        console.log("Flux audio Live (PCM 16kHz) démarré.");
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

export function playAudioChunk(base64Data, rate = 24000) {
    try {
        const binaryString = atob(base64Data);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }

        // Conversion du buffer brut en tableau d'échantillons 16-bit signés
        const buffer = new Int16Array(bytes.buffer);
        const floatSamples = new Float32Array(buffer.length);
        for (let i = 0; i < buffer.length; i++) {
            floatSamples[i] = buffer[i] / 32768.0;
        }

        // Lecture fluide via AudioContext au taux de sortie standard de 24 000 Hz
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const audioBuffer = audioCtx.createBuffer(1, floatSamples.length, rate);
        audioBuffer.copyToChannel(floatSamples, 0);

        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);
        source.start();
    } catch (e) {
        console.error("Erreur de lecture du chunk audio :", e);
    }
}
