'use strict';

let sharedAudioCtx = null;
let nextPlayTime = 0;
const activeAudioSources = new Set();

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
    let recognition = null;
    let recognitionStarted = false;
    let preflightEnabled = false;
    let awaitingContext = false;
    let stopped = false;
    let pendingChunks = [];
    let pendingChars = 0;
    const MAX_PREFLIGHT_CHUNKS = 256;
    const MAX_PREFLIGHT_CHARS = 8_000_000;

    const sendChunk = (pcmData) => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        try {
            socket.send({ action: 'audio_chunk', pcm_data: pcmData });
            return true;
        } catch (error) {
            console.warn("Envoi audio Live impossible :", error);
            return false;
        }
    };

    const flushPending = () => {
        const chunks = pendingChunks;
        pendingChunks = [];
        pendingChars = 0;
        for (const chunk of chunks) {
            if (!sendChunk(chunk)) return false;
        }
        return true;
    };

    const disablePreflight = () => {
        preflightEnabled = false;
        awaitingContext = false;
        if (recognition && recognitionStarted) {
            try { recognition.stop(); } catch (_) { /* already stopped */ }
        }
        recognitionStarted = false;
        flushPending();
    };

    const startRecognition = () => {
        if (
            !preflightEnabled || stopped || awaitingContext ||
            recognitionStarted || !recognition ||
            socket.readyState !== WebSocket.OPEN
        ) return;
        try {
            recognition.start();
            recognitionStarted = true;
        } catch (error) {
            // InvalidStateError means the browser is already starting/stopping
            // this recognizer; other failures disable preflight and preserve
            // the original continuous-audio fallback.
            if (error?.name !== 'InvalidStateError') {
                console.warn("Prétranscription Live indisponible :", error);
                disablePreflight();
            }
        }
    };

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

        const SpeechRecognitionClass =
            window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognitionClass) {
            try {
                recognition = new SpeechRecognitionClass();
                // Never send microphone audio to a remote Web Speech service.
                // Preflight is enabled only where the browser explicitly
                // exposes on-device recognition; otherwise Gemini's existing
                // direct-audio path remains in use.
                if (!('processLocally' in recognition)) {
                    recognition = null;
                } else {
                    recognition.processLocally = true;
                    recognition.lang = 'fr-FR';
                    recognition.continuous = false;
                    recognition.interimResults = false;
                    preflightEnabled = true;
                }
                if (recognition) recognition.onresult = (event) => {
                    const result = event.results?.[event.resultIndex ?? 0];
                    const transcript = result?.[0]?.transcript?.trim();
                    if (!transcript) {
                        disablePreflight();
                        return;
                    }
                    awaitingContext = true;
                    socket.send({
                        action: 'audio_transcript_ready',
                        text: transcript
                    });
                };
                if (recognition) {
                    recognition.onerror = (event) => {
                        console.warn("Prétranscription Live interrompue :", event?.error || "erreur");
                        disablePreflight();
                    };
                    recognition.onend = () => {
                        recognitionStarted = false;
                        if (!preflightEnabled || stopped || awaitingContext) return;
                        // No finalized transcript: send the captured audio through
                        // the legacy VAD path rather than silently losing speech.
                        flushPending();
                        startRecognition();
                    };
                } else {
                    preflightEnabled = false;
                }
            } catch (error) {
                console.warn("Reconnaissance vocale indisponible :", error);
                recognition = null;
                preflightEnabled = false;
            }
        }

        processor.onaudioprocess = (event) => {
            if (!socket || socket.readyState !== WebSocket.OPEN || stopped) return;
            startRecognition();
            const input = event.inputBuffer.getChannelData(0);
            const pcm16k = resampleFloat32(input, audioCtx.sampleRate, 16000);
            if (!pcm16k.length) return;
            const encoded = floatToPcm16Base64(pcm16k);

            if (!preflightEnabled) {
                sendChunk(encoded);
                return;
            }

            pendingChunks.push(encoded);
            pendingChars += encoded.length;
            if (
                pendingChunks.length > MAX_PREFLIGHT_CHUNKS ||
                pendingChars > MAX_PREFLIGHT_CHARS
            ) {
                // Bound browser memory even if speech recognition never returns.
                // The fallback remains compatible with Gemini's automatic VAD.
                disablePreflight();
            }
        };

        source.connect(processor);
        processor.connect(silentGain);
        silentGain.connect(audioCtx.destination);

        console.log(
            `Microphone Live prêt : ${audioCtx.sampleRate} Hz → PCM 16 kHz.` +
            (preflightEnabled ? " Rappel mémoire préalable activable." : " VAD direct (prétranscription indisponible).")
        );
        return {
            handleServerMessage(data) {
                if (data?.type !== 'audio_context_ready' || !awaitingContext || stopped) return;
                awaitingContext = false;
                flushPending();
                startRecognition();
            },
            stop() {
                stopped = true;
                pendingChunks = [];
                pendingChars = 0;
                if (recognition) {
                    recognition.onresult = null;
                    recognition.onerror = null;
                    recognition.onend = null;
                    try { recognition.stop(); } catch (_) { /* already stopped */ }
                }
                recognition = null;
                recognitionStarted = false;
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
        if (recognition) {
            try { recognition.stop(); } catch (_) { /* already stopped */ }
        }
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
        activeAudioSources.add(source);
        source.onended = () => activeAudioSources.delete(source);
        source.start(nextPlayTime);
        nextPlayTime += audioBuffer.duration;
    } catch (error) {
        console.error("Erreur de lecture du chunk audio Live :", error);
    }
}

export function interruptAudioPlayback() {
    for (const source of activeAudioSources) {
        try { source.stop(); } catch (_) { /* already stopped */ }
    }
    activeAudioSources.clear();
    nextPlayTime = 0;
}
