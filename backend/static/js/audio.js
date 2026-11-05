'use strict';

let sharedAudioCtx = null;
let nextPlayTime = 0;

function getAudioContext() {
    if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        sharedAudioCtx = new AudioContextClass();
    }
    if (sharedAudioCtx.state === 'suspended') {
        sharedAudioCtx.resume();
    }
    return sharedAudioCtx;
}

export async function playTextToSpeech(text) {
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

function resampleFloat32(input, sourceRate, targetRate) {
    if (!input?.length || !sourceRate || !targetRate) return new Float32Array(0);
    if (sourceRate === targetRate) return new Float32Array(input);
    const outputLength = Math.floor(input.length * targetRate / sourceRate);
    const output = new Float32Array(outputLength);
    const ratio = sourceRate / targetRate;
    for (let i = 0; i < outputLength; i++) {
        const position = i * ratio;
        const left = Math.floor(position);
        const right = Math.min(left + 1, input.length - 1);
        const fraction = position - left;
        output[i] = input[left] * (1 - fraction) + input[right] * fraction;
    }
    return output;
}

function floatToPcm16Base64(samples) {
    const bytes = new Uint8Array(samples.length * 2);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < samples.length; i++) {
        const value = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(i * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunkSize, bytes.length)));
    }
    return btoa(binary);
}

export async function initLiveAudioStream(socket) {
    let stream = null;
    let source = null;
    let processor = null;
    let silentGain = null;
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            },
            video: false
        });

        const audioCtx = getAudioContext();
        if (audioCtx.state !== 'running') await audioCtx.resume();

        source = audioCtx.createMediaStreamSource(stream);
        processor = audioCtx.createScriptProcessor(2048, 1, 1);
        silentGain = audioCtx.createGain();
        silentGain.gain.value = 0;

        processor.onaudioprocess = (event) => {
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            const input = event.inputBuffer.getChannelData(0);
            const pcm16k = resampleFloat32(input, audioCtx.sampleRate, 16000);
            if (!pcm16k.length) return;

            socket.send({
                action: 'audio_chunk',
                pcm_data: floatToPcm16Base64(pcm16k)
            });
        };

        source.connect(processor);
        processor.connect(silentGain);
        silentGain.connect(audioCtx.destination);

        console.log(`Microphone Live prêt : ${audioCtx.sampleRate} Hz → PCM 16 kHz.`);
        return {
            stop() {
                if (processor) {
                    processor.disconnect();
                    processor.onaudioprocess = null;
                }
                if (source) source.disconnect();
                if (silentGain) silentGain.disconnect();
                if (stream) stream.getTracks().forEach(track => track.stop());
            }
        };
    } catch (error) {
        console.error("Erreur d'accès au microphone :", error);
        if (stream) stream.getTracks().forEach(track => track.stop());
        if (processor) processor.disconnect();
        if (source) source.disconnect();
        if (silentGain) silentGain.disconnect();
        throw error;
    }
}

export async function playAudioChunk(base64Data, rate = 24000) {
    try {
        if (!base64Data || typeof base64Data !== 'string') return;
        const audioCtx = getAudioContext();
        if (audioCtx.state !== 'running') await audioCtx.resume();

        const binary = atob(base64Data);
        // Gemini can emit tiny empty frames; they contain no playable audio.
        if (binary.length < 8 || binary.length % 2 !== 0) return;

        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

        const view = new DataView(bytes.buffer);
        const samples = new Float32Array(bytes.length / 2);
        for (let i = 0; i < samples.length; i++) {
            samples[i] = view.getInt16(i * 2, true) / 32768;
        }

        const audioBuffer = audioCtx.createBuffer(1, samples.length, Number(rate) || 24000);
        audioBuffer.copyToChannel(samples, 0);

        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);

        const now = audioCtx.currentTime;
        if (nextPlayTime < now) nextPlayTime = now + 0.03;
        source.start(nextPlayTime);
        nextPlayTime += audioBuffer.duration;
    } catch (error) {
        console.error("Erreur de lecture du chunk audio Live :", error);
    }
}
