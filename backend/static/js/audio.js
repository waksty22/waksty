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
