
'use strict';

/* ============================================================
   CHAPPIE V19.3 — INTERFACE COGNITIVE
   Conversation • Voix • Vision • Mémoire • Émotions
   Gemini Live • Compétences • Objectifs • Profils vocaux
   ============================================================ */

/* =========================
   1. VARIABLES GLOBALES
   ========================= */

let recognition = null;
let speakingAudio = null;
let speakingAudioUrl = null;
let psychologyInterval = null;

let liveSocket = null;
let liveStream = null;
let liveCtx = null;
let liveProcessor = null;
let liveSource = null;
let liveNextTime = 0;
let liveActive = false;
let liveAudioSources = new Set();
let visionInterval = null;

let cameraStream = null;
let cameraStarting = false;
let visionBusy = false;
let messageBusy = false;
let speechGeneration = 0;

const $ = id => document.getElementById(id);

const CREATOR_ID = 'creator';
const DEFAULT_VOICE = 'fr-FR-HenriNeural';

const LIVE_SAMPLE_RATE = 16000;
const LIVE_OUTPUT_SAMPLE_RATE = 24000;


/* =========================
   2. OUTILS GÉNÉRAUX
   ========================= */

function setStatus(message) {
  const el = $('status');
  if (el) el.textContent = String(message ?? '');
}

function setText(id, message) {
  const el = $(id);
  if (el) el.textContent = String(message ?? '');
}

function setButtonDisabled(id, disabled) {
  const el = $(id);
  if (el) el.disabled = Boolean(disabled);
}

function getToken() {
  return ($('token')?.value || '').trim();
}

function headers() {
  const token = getToken();

  const result = {
    'Content-Type': 'application/json'
  };

  if (token) {
    result.Authorization = 'Bearer ' + token;
  }

  return result;
}

function requireToken() {
  if (getToken()) return true;

  setStatus('Saisis ton jeton API avant de continuer.');
  return false;
}

async function readResponse(response) {
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    return await response.json();
  }

  const text = await response.text();

  return text ? { detail: text } : {};
}

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {})
    }
  });

  const data = await readResponse(response);

  if (!response.ok) {
    const message =
      data.detail ||
      data.message ||
      data.error ||
      `Erreur HTTP ${response.status}`;

    throw new Error(
      typeof message === 'string'
        ? message
        : JSON.stringify(message)
    );
  }

  return data;
}

function formatDate(value) {
  if (!value) return 'Date inconnue';

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString('fr-FR');
}

function formatTime(value) {
  if (!value) return '--:--';

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit'
  });
}

function setOutput(message) {
  setText('out', message);
}

function jsonBody(data) {
  return JSON.stringify(data);
}


/* =========================
   3. TABLEAU DES ÉMOTIONS
   ========================= */

function renderEmotionsDashboard(psy, lastEvent = null) {
  if (!psy || typeof psy !== 'object') return;

  let container = $('state');

  if (!container) return;

  // Compatibilité avec l'ancien élément PRE.
  if (container.tagName === 'PRE') {
    const replacement = document.createElement('div');
    replacement.id = 'state';
    container.replaceWith(replacement);
    container = replacement;
  }

  const metrics = [
    {
      label: '⚡ Énergie',
      key: 'energy',
      color: '#10b981'
    },
    {
      label: '😊 Joie',
      key: 'joy',
      color: '#f59e0b'
    },
    {
      label: '🧐 Curiosité',
      key: 'curiosity',
      color: '#3b82f6'
    },
    {
      label: '😰 Peur / Inquiétude',
      key: 'fear',
      color: '#ef4444'
    },
    {
      label: '😤 Frustration',
      key: 'frustration',
      color: '#8b5cf6'
    },
    {
      label: '😢 Tristesse',
      key: 'sadness',
      color: '#64748b'
    }
  ];

  const panel = document.createElement('div');

  Object.assign(panel.style, {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    background: '#0b1525',
    padding: '14px',
    borderRadius: '12px',
    border: '1px solid #20334c',
    color: '#ffffff'
  });

  metrics.forEach(metric => {
    const rawValue = Number(psy[metric.key] ?? 50);

    const value = Math.max(
      0,
      Math.min(
        100,
        Number.isFinite(rawValue) ? Math.round(rawValue) : 50
      )
    );

    const color =
      metric.key === 'energy' && value < 25
        ? '#ef4444'
        : metric.color;

    const item = document.createElement('div');

    Object.assign(item.style, {
      display: 'flex',
      flexDirection: 'column',
      gap: '5px'
    });

    const labelRow = document.createElement('div');

    Object.assign(labelRow.style, {
      display: 'flex',
      justifyContent: 'space-between',
      gap: '8px',
      fontSize: '13px',
      color: '#aabbd0'
    });

    const label = document.createElement('span');
    label.textContent = metric.label;

    const number = document.createElement('span');
    number.textContent = `${value}%`;
    number.style.fontWeight = '700';
    number.style.color = '#ffffff';

    labelRow.append(label, number);

    const track = document.createElement('div');

    Object.assign(track.style, {
      width: '100%',
      height: '9px',
      background: '#131f31',
      border: '1px solid #2b3b52',
      borderRadius: '6px',
      overflow: 'hidden'
    });

    const bar = document.createElement('div');

    Object.assign(bar.style, {
      width: `${value}%`,
      height: '100%',
      background: color,
      borderRadius: '6px',
      transition: 'width 0.4s ease, background 0.4s ease'
    });

    track.appendChild(bar);
    item.append(labelRow, track);
    panel.appendChild(item);
  });

  if (lastEvent) {
    const eventBox = document.createElement('div');

    Object.assign(eventBox.style, {
      marginTop: '4px',
      paddingTop: '10px',
      borderTop: '1px solid #2b3b52',
      fontSize: '13px',
      color: '#9de4f5',
      overflowWrap: 'anywhere'
    });

    const title = document.createElement('strong');
    title.textContent = '🧠 Dernier événement : ';

    const description = document.createElement('span');
    description.textContent = String(lastEvent);

    eventBox.append(title, description);
    panel.appendChild(eventBox);
  }

  container.replaceChildren(panel);
}


/* =========================
   4. ACTUALISATION ÉMOTIONNELLE
   ========================= */

async function fetchPsychology() {
  if (!getToken()) return;

  try {
    const data = await apiRequest('/api/emotions/creator');

    if (data.psychology) {
      renderEmotionsDashboard(data.psychology);
    }
  } catch (error) {
    console.warn(
      'Actualisation émotionnelle indisponible :',
      error.message
    );
  }
}

function startPsychologyPolling() {
  if (psychologyInterval) {
    clearInterval(psychologyInterval);
  }

  // Une seule boucle d'actualisation.
  psychologyInterval = setInterval(() => {
    if (document.visibilityState === 'visible') {
      fetchPsychology();
    }
  }, 30000);
}


/* =========================
   5. PREMIER RÉVEIL
   ========================= */

let greetingInProgress = false;

async function checkInitialGreeting() {
  const output = $('out');

  if (!output || !getToken() || greetingInProgress) {
    return;
  }

  const currentText = output.textContent.trim();

  const waiting =
    currentText === '' ||
    currentText.includes('En attente de ton message');

  if (!waiting) return;

  greetingInProgress = true;
  setStatus('Chappie s’éveille…');

  try {
    const data = await apiRequest('/api/chat', {
      method: 'POST',
      body: jsonBody({
        user_id: CREATOR_ID,
        message:
          "[Système : Si tu es en phase de premier réveil, prends l'initiative de parler. Utilise des phrases courtes, simples et adaptées à ton niveau de langage. Ne prétends pas posséder des expériences que tu n'as pas vécues.]"
      })
    });

    if (data.reply) {
      setOutput(data.reply);

      if (data.psychology) {
        renderEmotionsDashboard(data.psychology);
      }

      setStatus('Chappie a pris l’initiative !');
      await speak(data.reply);
    } else {
      setStatus('Chappie est prêt.');
    }
  } catch (error) {
    console.warn('Premier réveil :', error.message);
    setStatus('Interface prête. Vérifie le jeton et le serveur.');
  } finally {
    greetingInProgress = false;
  }
}


/* =========================
   6. CONVERSATION TEXTE
   ========================= */

async function sendMessage() {
  const messageInput = $('msg');

  if (!messageInput || messageBusy) return;

  const message = messageInput.value.trim();

  if (!message) {
    setStatus('Écris un message avant de l’envoyer.');
    return;
  }

  if (!requireToken()) return;

  messageBusy = true;
  setButtonDisabled('sendBtn', true);

  setStatus('Chappie réfléchit…');
  setOutput('Chappie réfléchit…');

  try {
    const data = await apiRequest('/api/chat', {
      method: 'POST',
      body: jsonBody({
        user_id: CREATOR_ID,
        message
      })
    });

    if (typeof data.reply !== 'string') {
      throw new Error('La réponse du serveur ne contient pas de texte.');
    }

    setOutput(data.reply);

    if (data.psychology) {
      renderEmotionsDashboard(data.psychology);
    }

    messageInput.value = '';
    setStatus('Réponse reçue.');

    await speak(data.reply);
  } catch (error) {
    setOutput('Erreur : ' + error.message);

    setStatus(
      'Vérifie le jeton, la connexion et la configuration Gemini.'
    );
  } finally {
    messageBusy = false;
    setButtonDisabled('sendBtn', false);
  }
}


/* =========================
   7. SYNTHÈSE VOCALE
   ========================= */

async function speak(text) {
  if (!text || typeof text !== 'string') return;

  if (!getToken()) {
    setStatus('Réponse écrite prête. Jeton requis pour la voix.');
    return;
  }

  // Invalide une éventuelle lecture précédente.
  const generation = ++speechGeneration;

  if (speakingAudio) {
    speakingAudio.pause();
    speakingAudio.onended = null;
    speakingAudio.onerror = null;
    speakingAudio = null;
  }

  if (speakingAudioUrl) {
    URL.revokeObjectURL(speakingAudioUrl);
    speakingAudioUrl = null;
  }

  try {
    const response = await fetch('/api/speak', {
      method: 'POST',
      headers: headers(),
      body: jsonBody({
        text,
        voice: DEFAULT_VOICE
      })
    });

    if (!response.ok) {
      const errorData = await readResponse(response);

      throw new Error(
        errorData.detail ||
        'La synthèse vocale est indisponible.'
      );
    }

    const blob = await response.blob();

    if (!blob.size) {
      throw new Error('Le serveur a renvoyé un fichier audio vide.');
    }

    // Une nouvelle lecture a pu être demandée pendant le chargement.
    if (generation !== speechGeneration) return;

    speakingAudioUrl = URL.createObjectURL(blob);
    speakingAudio = new Audio(speakingAudioUrl);

    speakingAudio.playbackRate = 1;

    speakingAudio.onended = () => {
      if (generation !== speechGeneration) return;

      if (speakingAudioUrl) {
        URL.revokeObjectURL(speakingAudioUrl);
      }

      speakingAudioUrl = null;
      speakingAudio = null;

      setStatus('Prêt.');
    };

    speakingAudio.onerror = () => {
      if (generation !== speechGeneration) return;

      if (speakingAudioUrl) {
        URL.revokeObjectURL(speakingAudioUrl);
      }

      speakingAudioUrl = null;
      speakingAudio = null;

      setStatus('Erreur de lecture audio.');
    };

    setStatus('Lecture vocale en cours…');

    await speakingAudio.play();
  } catch (error) {
    if (generation !== speechGeneration) return;

    console.warn('Synthèse vocale :', error.message);

    setStatus(
      'Réponse écrite prête ; lecture vocale indisponible.'
    );
  }
}

function stopSpeech() {
  // Invalide les requêtes audio encore en cours.
  speechGeneration++;

  if (speakingAudio) {
    speakingAudio.pause();

    try {
      speakingAudio.currentTime = 0;
    } catch (_) {}

    speakingAudio.onended = null;
    speakingAudio.onerror = null;
    speakingAudio = null;
  }

  if (speakingAudioUrl) {
    URL.revokeObjectURL(speakingAudioUrl);
    speakingAudioUrl = null;
  }

  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }

  setStatus('Lecture arrêtée.');
}


/* =========================
   8. DICTÉE VOCALE
   ========================= */

function toggleMic() {
  const micButton = $('micBtn');

  const SpeechRecognitionAPI =
    window.SpeechRecognition ||
    window.webkitSpeechRecognition;

  if (!SpeechRecognitionAPI) {
    setStatus(
      'La dictée vocale nécessite un navigateur compatible, par exemple Chrome.'
    );
    return;
  }

  if (recognition) {
    try {
      recognition.stop();
    } catch (_) {}

    return;
  }

  try {
    const instance = new SpeechRecognitionAPI();

    recognition = instance;
    instance.lang = 'fr-FR';
    instance.interimResults = true;
    instance.continuous = false;
    instance.maxAlternatives = 1;

    instance.onresult = event => {
      let transcript = '';

      for (
        let i = event.resultIndex;
        i < event.results.length;
        i++
      ) {
        transcript += event.results[i][0].transcript;
      }

      const input = $('msg');

      if (input) {
        input.value = transcript;
      }
    };

    instance.onerror = event => {
      setStatus('Dictée vocale : ' + event.error);
    };

    instance.onend = () => {
      if (recognition === instance) {
        recognition = null;
      }

      if (micButton) {
        micButton.textContent = '🎙️ Dicter';
      }

      setStatus('Dictée terminée. Vérifie le texte puis envoie-le.');
    };

    if (micButton) {
      micButton.textContent = '⏹️ Arrêter dictée';
    }

    setStatus('Je t’écoute…');
    instance.start();
  } catch (error) {
    recognition = null;

    if (micButton) {
      micButton.textContent = '🎙️ Dicter';
    }

    setStatus('Impossible de démarrer la dictée : ' + error.message);
  }
}


/* =========================
   9. MÉMOIRE ET HISTORIQUE
   ========================= */

async function loadSummary() {
  try {
    const data = await apiRequest('/api/memory/summary');

    setText(
      'summary',
      data.summary || 'Aucun résumé enregistré pour le moment.'
    );
  } catch (error) {
    setText('summary', 'Erreur de chargement : ' + error.message);
  }
}

async function loadMoodHistory() {
  try {
    const data = await apiRequest('/api/mood/history?limit=10');

    if (!Array.isArray(data.events)) {
      throw new Error('Format de réponse inattendu.');
    }

    if (data.events.length === 0) {
      setText(
        'summary',
        'Aucun événement d’humeur enregistré pour le moment.'
      );
      return;
    }

    let text = '📜 Historique des 10 dernières humeurs\n\n';

    data.events.forEach(event => {
      const date = formatTime(event.created_at);

      const valence = Number(event.valence);
      const sign = valence > 0 ? '+' : '';

      text +=
        `• [${date}] ${event.event || 'Événement'} ` +
        `(Valence : ${sign}${Number.isFinite(valence) ? valence : '—'})\n`;
    });

    setText('summary', text);
  } catch (error) {
    setText('summary', 'Erreur d’historique : ' + error.message);
  }
}

async function loadDreams() {
  try {
    const data = await apiRequest('/api/dreams/creator');

    if (!Array.isArray(data.dreams)) {
      throw new Error('Format de réponse inattendu.');
    }

    if (data.dreams.length === 0) {
      setText('summary', 'Aucun rêve simulé enregistré pour le moment.');
      return;
    }

    let text = '🌙 Derniers rêves simulés de Chappie\n\n';

    data.dreams.forEach(dream => {
      text +=
        `• [${formatDate(dream.created_at)}]\n` +
        `  ${dream.content || 'Contenu indisponible'}\n\n`;
    });

    setText('summary', text);
  } catch (error) {
    setText('summary', 'Erreur de chargement des rêves : ' + error.message);
  }
}

async function loadThoughts() {
  try {
    const data = await apiRequest('/api/thoughts/creator');

    if (!Array.isArray(data.thoughts)) {
      throw new Error('Format de réponse inattendu.');
    }

    if (data.thoughts.length === 0) {
      setText(
        'summary',
        'Aucune pensée métacognitive enregistrée pour le moment.'
      );
      return;
    }

    let text = '🧠 Dernières pensées de Chappie\n\n';

    data.thoughts.forEach(thought => {
      text +=
        `• [${formatDate(thought.created_at)}]\n` +
        `  ${thought.content || 'Contenu indisponible'}\n\n`;
    });

    setText('summary', text);
  } catch (error) {
    setText('summary', 'Erreur de chargement des pensées : ' + error.message);
  }
}


/* =========================
   10. COMPÉTENCES COGNITIVES
   ========================= */

async function loadSkills() {
  try {
    const data = await apiRequest('/api/skills/creator');

    if (!Array.isArray(data.skills)) {
      throw new Error('Format de réponse inattendu.');
    }

    if (data.skills.length === 0) {
      setText('summary', 'Aucune compétence enregistrée pour le moment.');
      return;
    }

    const maturity = Number(
      data.cognitive_profile?.global_maturity ??
      data.average_level ??
      1
    );

    let text =
      '🎓 Écosystème cognitif de Chappie\n' +
      `Maturité globale : ${maturity.toFixed(1)}/10\n\n`;

    data.skills.forEach(skill => {
      const level = Number(skill.level ?? 0);
      const xp = Number(skill.xp ?? 0);
      const progress = Math.max(0, Math.min(100, Math.round(xp % 100)));

      text +=
        `🔹 ${(skill.skill_name || 'Compétence').toUpperCase()}\n` +
        `   Niveau : ${Math.round(level)}\n` +
        `   XP : ${Math.round(xp)} — ${progress}% du prochain palier\n` +
        `   Preuve : ${skill.evidence || 'Aucune'}\n\n`;
    });

    const behavior = data.cognitive_profile?.behavior;

    if (behavior) {
      text +=
        '⚙️ Profil comportemental\n' +
        `• Complexité : ${behavior.response_complexity ?? '—'}\n` +
        `• Vocabulaire : ${behavior.vocabulary_richness ?? '—'}\n` +
        `• Humour : ${behavior.humor_description ?? '—'}\n` +
        `• Incertitude : ${behavior.uncertainty_handling ?? '—'}\n`;
    }

    setText('summary', text);
  } catch (error) {
    setText('summary', 'Erreur de chargement des compétences : ' + error.message);
  }
}


/* =========================
   11. RÉINITIALISATION DE CHAPPIE
   ========================= */

async function resetLife() {
  if (!requireToken()) return;

  const confirmed = window.confirm(
    '⚠️ Es-tu sûr de vouloir réinitialiser Chappie à zéro ?\n\n' +
    'Cette action peut effacer ses souvenirs, son historique et ses données ' +
    'selon le fonctionnement de ton serveur. Vérifie que tu disposes d’une sauvegarde.'
  );

  if (!confirmed) return;

  setStatus('Réinitialisation de Chappie en cours…');

  try {
    const data = await apiRequest('/api/reset-life', {
      method: 'POST'
    });

    setText(
      'summary',
      data.message ||
      'Réinitialisation demandée. Vérifie les données renvoyées par le serveur.'
    );

    setOutput('Bip… Où suis-je ? Bonjour… c’est quoi cet endroit ?');

    setStatus('Réinitialisation terminée.');
    await fetchPsychology();
  } catch (error) {
    setStatus('Erreur de réinitialisation : ' + error.message);
  }
}


/* =========================
   12. OBJECTIFS ET APPRENTISSAGE
   ========================= */

async function loadGoals() {
  try {
    const data = await apiRequest('/api/goals');

    if (!Array.isArray(data.goals)) {
      throw new Error('Format de réponse inattendu.');
    }

    if (data.goals.length === 0) {
      setText('summary', 'Aucun objectif actif pour le moment.');
      return;
    }

    let text = '🎯 Objectifs de Chappie\n\n';

    data.goals.forEach(goal => {
      const progress = Math.max(
        0,
        Math.min(100, Math.round(Number(goal.progress) || 0))
      );

      text += `📌 ${goal.title || 'Objectif sans titre'} (${progress}%)\n`;

      if (Array.isArray(goal.steps)) {
        goal.steps.forEach(step => {
          const completed = step.status === 'completed';

          text +=
            `   ${completed ? '✅' : '⏳'} ` +
            `${step.description || 'Étape sans description'}\n`;
        });
      }

      text += '\n';
    });

    setText('summary', text);
  } catch (error) {
    setText('summary', 'Erreur de chargement des objectifs : ' + error.message);
  }
}

async function consolidate() {
  if (!requireToken()) return;

  setStatus('Consolidation de la mémoire en cours…');

  try {
    const data = await apiRequest('/api/memory/consolidate', {
      method: 'POST'
    });

    setText(
      'summary',
      data.summary || 'Aucun échange à résumer.'
    );

    setStatus('Mémoire consolidée.');
  } catch (error) {
    setText('summary', 'Erreur : ' + error.message);
    setStatus('Consolidation impossible.');
  }
}


/* =========================
   13. ENCODAGE AUDIO
   ========================= */

function b64(bytes) {
  let result = '';
  const chunkSize = 0x8000;

  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(
      i,
      Math.min(i + chunkSize, bytes.length)
    );

    result += String.fromCharCode(...chunk);
  }

  return btoa(result);
}

function fromB64(value) {
  const raw = atob(value);
  const bytes = new Uint8Array(raw.length);

  for (let i = 0; i < raw.length; i++) {
    bytes[i] = raw.charCodeAt(i);
  }

  return bytes;
}

function pcm16Base64(float32) {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);

  for (let i = 0; i < float32.length; i++) {
    const sample = Math.max(-1, Math.min(1, float32[i]));

    view.setInt16(
      i * 2,
      sample < 0 ? sample * 32768 : sample * 32767,
      true
    );
  }

  return b64(new Uint8Array(buffer));
}

function resample(input, fromRate, toRate) {
  if (fromRate === toRate) {
    return new Float32Array(input);
  }

  if (!fromRate || !toRate || input.length === 0) {
    return new Float32Array(0);
  }

  const ratio = fromRate / toRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(
      input.length,
      Math.floor((i + 1) * ratio)
    );

    let sum = 0;
    let count = 0;

    for (let j = start; j < end; j++) {
      sum += input[j];
      count++;
    }

    output[i] = count > 0 ? sum / count : 0;
  }

  return output;
}


/* =========================
   14. GEMINI LIVE — VISION
   ========================= */

function startLiveVision() {
  stopLiveVision();

  const video = $('camera');

  if (!video || !cameraStream) return;

  const canvas = document.createElement('canvas');
  canvas.width = 480;
  canvas.height = 360;

  const context = canvas.getContext('2d');

  if (!context) return;

  visionInterval = setInterval(() => {
    if (
      !liveActive ||
      !liveSocket ||
      liveSocket.readyState !== WebSocket.OPEN ||
      !video.videoWidth ||
      !video.videoHeight
    ) {
      return;
    }

    try {
      context.drawImage(
        video,
        0,
        0,
        canvas.width,
        canvas.height
      );

      const imageBase64 = canvas
        .toDataURL('image/jpeg', 0.4)
        .split(',')[1];

      if (!imageBase64) return;

      liveSocket.send(JSON.stringify({
        video: {
          mimeType: 'image/jpeg',
          data: imageBase64
        }
      }));
    } catch (error) {
      console.warn('Image Live non envoyée :', error.message);
    }
  }, 1500);
}

function stopLiveVision() {
  if (visionInterval) {
    clearInterval(visionInterval);
    visionInterval = null;
  }
}


/* =========================
   15. GEMINI LIVE — CONVERSATION
   ========================= */

async function toggleLive() {
  if (liveActive || liveSocket) {
    stopLive();
    return;
  }

  if (!requireToken()) {
    setText(
      'liveStatus',
      'Saisis ton jeton API avant de démarrer.'
    );
    return;
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    setText(
      'liveStatus',
      'Le microphone nécessite un navigateur compatible et une connexion sécurisée.'
    );
    return;
  }

  try {
    setText('liveStatus', 'Demande d’accès au microphone…');

    liveStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    liveCtx = new (
      window.AudioContext ||
      window.webkitAudioContext
    )();

    await liveCtx.resume();

    const protocol =
      location.protocol === 'https:' ? 'wss:' : 'ws:';

    const token = encodeURIComponent(getToken());

    liveSocket = new WebSocket(
      `${protocol}//${location.host}/ws/live?token=${token}`
    );

    const socket = liveSocket;

    socket.onopen = () => {
      if (socket !== liveSocket) return;

      liveActive = true;

      const liveButton = $('liveBtn');

      if (liveButton) {
        liveButton.textContent = '⏹ Arrêter la conversation';
      }

      setText('liveStatus', 'Conversation Live connectée.');

      try {
        liveSource = liveCtx.createMediaStreamSource(liveStream);

        liveProcessor = liveCtx.createScriptProcessor(
          2048,
          1,
          1
        );

        liveProcessor.onaudioprocess = event => {
          if (
            !liveActive ||
            !liveSocket ||
            liveSocket.readyState !== WebSocket.OPEN
          ) {
            return;
          }

          const input = event.inputBuffer.getChannelData(0);

          const pcm = resample(
            input,
            liveCtx.sampleRate,
            LIVE_SAMPLE_RATE
          );

          if (!pcm.length) return;

          try {
            liveSocket.send(JSON.stringify({
              audio: pcm16Base64(pcm)
            }));
          } catch (error) {
            console.warn('Envoi audio impossible :', error.message);
          }
        };

        liveSource.connect(liveProcessor);

        // Le processeur est relié à une destination silencieuse
        // pour rester actif sans renvoyer le micro dans les haut-parleurs.
        const silentGain = liveCtx.createGain();
        silentGain.gain.value = 0;

        liveProcessor.connect(silentGain);
        silentGain.connect(liveCtx.destination);

        liveProcessor._silentGain = silentGain;

        if (cameraStream) {
          startLiveVision();
        }
      } catch (error) {
        setText(
          'liveStatus',
          'Erreur de préparation audio : ' + error.message
        );

        stopLive();
      }
    };

    socket.onmessage = event => {
      if (socket !== liveSocket) return;

      let data;

      try {
        data = JSON.parse(event.data);
      } catch (error) {
        console.warn('Message Live illisible.');
        return;
      }

      if (data.status) {
        setText('liveStatus', data.status);
      }

      if (data.interrupt) {
        for (const source of liveAudioSources) {
          try {
            source.stop();
          } catch (_) {}
        }

        liveAudioSources.clear();

        liveNextTime = liveCtx
          ? liveCtx.currentTime
          : 0;

        setOutput('Chappie : ');
      }

      if (data.text) {
        const output = $('out');

        if (output) {
          if (
            output.textContent.startsWith('En attente') ||
            output.textContent === 'Chappie : ' ||
            output.textContent === 'Chappie réfléchit…'
          ) {
            output.textContent = 'Chappie : ' + data.text;
          } else {
            output.textContent += data.text;
          }
        }
      }

      if (data.audio) {
        playLiveAudio(
          data.audio,
          data.sample_rate || LIVE_OUTPUT_SAMPLE_RATE
        );
      }

      if (data.psychology) {
        renderEmotionsDashboard(data.psychology);
      }

      if (data.error) {
        setText('liveStatus', 'Erreur : ' + data.error);
      }
    };

    socket.onerror = () => {
      if (socket === liveSocket) {
        setText(
          'liveStatus',
          'Erreur WebSocket. Vérifie le serveur et le jeton.'
        );
      }
    };

    socket.onclose = () => {
      if (socket !== liveSocket) return;

      stopLive(false);

      setText('liveStatus', 'Session Live terminée.');
    };
  } catch (error) {
    setText(
      'liveStatus',
      'Impossible de démarrer : ' + error.message
    );

    stopLive();
  }
}


/* =========================
   16. LECTURE AUDIO GEMINI LIVE
   ========================= */

function playLiveAudio(encoded, rate = LIVE_OUTPUT_SAMPLE_RATE) {
  if (!liveCtx || !encoded) return;

  try {
    const bytes = fromB64(encoded);

    if (bytes.length < 2) return;

    // IMPORTANT :
    // Cette conversion suppose que le serveur renvoie du PCM signé
    // 16 bits little-endian, et non du Float32 ou un fichier MP3.
    const sampleCount = Math.floor(bytes.length / 2);

    const view = new DataView(
      bytes.buffer,
      bytes.byteOffset,
      bytes.byteLength
    );

    const samples = new Float32Array(sampleCount);

    for (let i = 0; i < sampleCount; i++) {
      samples[i] = view.getInt16(i * 2, true) / 32768;
    }

    const sampleRate = Number(rate) || LIVE_OUTPUT_SAMPLE_RATE;

    const audioBuffer = liveCtx.createBuffer(
      1,
      samples.length,
      sampleRate
    );

    audioBuffer.copyToChannel(samples, 0);

    const source = liveCtx.createBufferSource();

    source.buffer = audioBuffer;
    source.connect(liveCtx.destination);

    liveAudioSources.add(source);

    source.onended = () => {
      liveAudioSources.delete(source);
    };

    const now = liveCtx.currentTime;

    if (liveNextTime < now) {
      liveNextTime = now + 0.12;
    }

    source.start(liveNextTime);

    liveNextTime += audioBuffer.duration;
  } catch (error) {
    console.error(
      'Erreur de lecture audio Live :',
      error
    );
  }
}


/* =========================
   17. ARRÊT GEMINI LIVE
   ========================= */

function stopLive(closeSocket = true) {
  liveActive = false;

  stopLiveVision();

  if (liveProcessor) {
    try {
      liveProcessor.disconnect();
      liveProcessor.onaudioprocess = null;

      if (liveProcessor._silentGain) {
        liveProcessor._silentGain.disconnect();
      }
    } catch (_) {}
  }

  if (liveSource) {
    try {
      liveSource.disconnect();
    } catch (_) {}
  }

  if (liveStream) {
    try {
      liveStream.getTracks().forEach(track => track.stop());
    } catch (_) {}
  }

  const socket = liveSocket;

  // Invalide immédiatement l'ancienne connexion.
  liveSocket = null;
  window.liveSocket = null;

  if (socket && closeSocket) {
    try {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;

      if (socket.readyState < WebSocket.CLOSING) {
        socket.close();
      }
    } catch (_) {}
  }

  for (const source of liveAudioSources) {
    try {
      source.stop();
    } catch (_) {}
  }

  liveAudioSources.clear();

  if (liveCtx) {
    try {
      liveCtx.close();
    } catch (_) {}
  }

  liveStream = null;
  liveCtx = null;
  liveProcessor = null;
  liveSource = null;
  liveNextTime = 0;

  const button = $('liveBtn');

  if (button) {
    button.textContent = '▶ Démarrer la conversation live';
  }

  if (closeSocket) {
    setText('liveStatus', 'Conversation arrêtée.');
  }
}


/* =========================
   18. VISION : CAMÉRA
   ========================= */

async function startCamera() {
  if (cameraStream || cameraStarting) return;

  if (!navigator.mediaDevices?.getUserMedia) {
    setText(
      'visionOut',
      'La caméra nécessite HTTPS ou un environnement local sécurisé.'
    );
    return;
  }

  cameraStarting = true;

  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 720 }
      },
      audio: false
    });

    const video = $('camera');

    if (!video) {
      cameraStream.getTracks().forEach(track => track.stop());
      cameraStream = null;

      throw new Error('Élément vidéo camera introuvable dans le HTML.');
    }

    video.srcObject = cameraStream;
    video.playsInline = true;
    video.muted = true;

    try {
      await video.play();
    } catch (_) {
      // Certains navigateurs attendent une action de l'utilisateur.
    }

    setText(
      'visionOut',
      'Caméra active. Chappie peut analyser une image.'
    );

    if (liveActive && liveSocket) {
      startLiveVision();
    }
  } catch (error) {
    cameraStream = null;

    setText(
      'visionOut',
      'Accès caméra impossible : ' + error.message
    );
  } finally {
    cameraStarting = false;
  }
}

function stopCamera() {
  stopLiveVision();

  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      try {
        track.stop();
      } catch (_) {}
    });
  }

  cameraStream = null;

  const video = $('camera');

  if (video) {
    video.pause();
    video.srcObject = null;
  }

  setText('visionOut', 'Caméra inactive.');
}


/* =========================
   19. ANALYSE VISUELLE
   ========================= */

async function captureVision() {
  if (visionBusy) return;

  if (!requireToken()) return;

  const video = $('camera');

  if (
    !cameraStream ||
    !video ||
    !video.videoWidth ||
    !video.videoHeight
  ) {
    setText(
      'visionOut',
      'Active la caméra et attends que l’image apparaisse.'
    );
    return;
  }

  const canvas = document.createElement('canvas');

  const scale = Math.min(
    1,
    960 / video.videoWidth,
    960 / video.videoHeight
  );

  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);

  const context = canvas.getContext('2d');

  if (!context) {
    setText('visionOut', 'Impossible de préparer l’image.');
    return;
  }

  context.drawImage(
    video,
    0,
    0,
    canvas.width,
    canvas.height
  );

  let imageData;

  try {
    imageData = canvas.toDataURL('image/jpeg', 0.65);
  } catch (error) {
    setText('visionOut', 'Impossible de capturer l’image.');
    return;
  }

  visionBusy = true;

  setText('visionOut', 'Chappie observe l’image…');

  try {
    const visionData = await apiRequest('/api/vision/analyze', {
      method: 'POST',
      body: jsonBody({
        image_data_url: imageData,
        prompt:
          'Décris ce que tu vois. Distingue les éléments certains ' +
          'des suppositions. Décris les objets, les couleurs, les ' +
          'positions et le contexte. Si une personne est visible, ' +
          'décris son apparence sans chercher à déterminer son identité.'
      })
    });

    const description = visionData.description;

    if (!description) {
      throw new Error('Aucune description reçue du serveur.');
    }

    setText(
      'visionOut',
      'Ce que Chappie voit :\n' + description +
      '\n\nChappie prépare sa réponse…'
    );

    const chatData = await apiRequest('/api/chat', {
      method: 'POST',
      body: jsonBody({
        user_id: CREATOR_ID,
        message:
          'Tu viens d’analyser une image avec ta caméra. ' +
          'Voici la description obtenue :\n' +
          description +
          '\nRéagis naturellement à ce que tu observes et ' +
          'explique-moi ce que tu en comprends.'
      })
    });

    if (!chatData.reply) {
      throw new Error('Chappie n’a pas renvoyé de réponse.');
    }

    setText('visionOut', 'Ce que Chappie voit :\n' + description);
    setOutput(chatData.reply);

    if (chatData.psychology) {
      renderEmotionsDashboard(chatData.psychology);
    }

    setStatus('Image analysée et réponse reçue.');

    await speak(chatData.reply);
  } catch (error) {
    setText(
      'visionOut',
      'Erreur caméra : ' + error.message
    );

    setStatus('Vérifie le jeton et la configuration du serveur.');
  } finally {
    visionBusy = false;
  }
}


/* =========================
   20. ENREGISTREMENT AUDIO WAV
   ========================= */

function wavBlob(floatSamples, sampleRate) {
  const targetRate = 16000;

  const samples = resample(
    floatSamples,
    sampleRate,
    targetRate
  );

  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, value) => {
    for (let i = 0; i < value.length; i++) {
      view.setUint8(offset + i, value.charCodeAt(i));
    }
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);

  writeString(8, 'WAVE');
  writeString(12, 'fmt ');

  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);

  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);

  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);

  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));

    view.setInt16(
      44 + i * 2,
      sample < 0 ? sample * 32768 : sample * 32767,
      true
    );
  }

  return new Blob([buffer], {
    type: 'audio/wav'
  });
}


/* =========================
   21. PROFILS VOCAUX
   ========================= */

async function recordVoice(mode) {
  if (!requireToken()) return;

  if (!navigator.mediaDevices?.getUserMedia) {
    setText('voiceStatus', 'Microphone non disponible.');
    return;
  }

  const name = $('voiceName')?.value.trim() || '';

  if (mode === 'enroll' && !name) {
    setText('voiceStatus', 'Saisis un nom de profil.');
    return;
  }

  if (mode !== 'enroll' && mode !== 'identify') {
    setText('voiceStatus', 'Mode vocal inconnu.');
    return;
  }

  let stream = null;
  let context = null;
  let source = null;
  let processor = null;
  let muteGain = null;

  const chunks = [];

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    context = new (
      window.AudioContext ||
      window.webkitAudioContext
    )();

    await context.resume();

    const sampleRate = context.sampleRate;

    source = context.createMediaStreamSource(stream);

    processor = context.createScriptProcessor(
      4096,
      1,
      1
    );

    muteGain = context.createGain();
    muteGain.gain.value = 0;

    processor.onaudioprocess = event => {
      chunks.push(
        new Float32Array(
          event.inputBuffer.getChannelData(0)
        )
      );
    };

    source.connect(processor);
    processor.connect(muteGain);
    muteGain.connect(context.destination);

    const seconds = mode === 'enroll' ? 8 : 5;

    setText(
      'voiceStatus',
      `Enregistrement ${mode === 'enroll' ? 'du profil' : 'de comparaison'}… parle naturellement.`
    );

    await new Promise(resolve => {
      window.setTimeout(resolve, seconds * 1000);
    });

    processor.disconnect();
    source.disconnect();
    muteGain.disconnect();

    stream.getTracks().forEach(track => track.stop());

    await context.close();

    const totalLength = chunks.reduce(
      (sum, chunk) => sum + chunk.length,
      0
    );

    if (!totalLength) {
      throw new Error('Aucun son enregistré.');
    }

    const samples = new Float32Array(totalLength);

    let offset = 0;

    for (const chunk of chunks) {
      samples.set(chunk, offset);
      offset += chunk.length;
    }

    const blob = wavBlob(samples, sampleRate);

    const endpoint =
      mode === 'enroll'
        ? '/api/voice-profiles/' + encodeURIComponent(name)
        : '/api/voice-profiles-identify';

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + getToken(),
        'Content-Type': 'audio/wav'
      },
      body: blob
    });

    const data = await readResponse(response);

    if (!response.ok) {
      throw new Error(
        data.detail || 'Erreur lors du traitement du profil vocal.'
      );
    }

    if (mode === 'enroll') {
      setText(
        'voiceStatus',
        'Profil enregistré : ' + (data.profile_name || name)
      );
    } else {
      const score =
        data.score === undefined
          ? '—'
          : data.score;

      setText(
        'voiceStatus',
        `Résultat : ${data.profile_name || 'Personne non reconnue'} (score ${score})`
      );
    }
  } catch (error) {
    setText(
      'voiceStatus',
      'Profils vocaux : ' + error.message
    );
  } finally {
    if (processor) {
      try {
        processor.disconnect();
      } catch (_) {}
    }

    if (source) {
      try {
        source.disconnect();
      } catch (_) {}
    }

    if (muteGain) {
      try {
        muteGain.disconnect();
      } catch (_) {}
    }

    if (stream) {
      stream.getTracks().forEach(track => {
        try {
          track.stop();
        } catch (_) {}
      });
    }

    if (context && context.state !== 'closed') {
      try {
        await context.close();
      } catch (_) {}
    }
  }
}


/* =========================
   22. INITIALISATION
   ========================= */

function initializeChappie() {
  setStatus(
    'Interface chargée. Jeton requis pour les fonctions protégées.'
  );

  console.info('Chappie V19.3 : interface prête.');

  const messageInput = $('msg');

  if (messageInput) {
    messageInput.addEventListener('keydown', event => {
      if (
        event.key === 'Enter' &&
        !event.shiftKey &&
        !event.isComposing
      ) {
        event.preventDefault();
        sendMessage();
      }
    });
  }

  // Les données ne sont chargées que si un jeton est disponible.
  if (getToken()) {
    fetchPsychology();

    window.setTimeout(() => {
      checkInitialGreeting();
    }, 1000);
  }

  startPsychologyPolling();

  // Rafraîchit les émotions après la saisie du jeton.
  const tokenInput = $('token');

  if (tokenInput) {
    tokenInput.addEventListener('change', () => {
      if (getToken()) {
        fetchPsychology();
      }
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener(
    'DOMContentLoaded',
    initializeChappie,
    { once: true }
  );
} else {
  initializeChappie();
}


/* =========================
   23. FERMETURE ET NETTOYAGE
   ========================= */

window.addEventListener('pagehide', () => {
  stopLive();
  stopLiveVision();

  if (recognition) {
    try {
      recognition.abort();
    } catch (_) {}

    recognition = null;
  }

  if (speakingAudio) {
    speakingAudio.pause();
    speakingAudio = null;
  }

  if (speakingAudioUrl) {
    URL.revokeObjectURL(speakingAudioUrl);
    speakingAudioUrl = null;
  }

  if (cameraStream) {
    cameraStream.getTracks().forEach(track => {
      try {
        track.stop();
      } catch (_) {}
    });

    cameraStream = null;
  }

  if (psychologyInterval) {
    clearInterval(psychologyInterval);
    psychologyInterval = null;
  }
});


/* =========================
   24. FONCTIONS POUR LE HTML
   ========================= */

window.sendMessage = sendMessage;
window.speak = speak;
window.stopSpeech = stopSpeech;
window.toggleMic = toggleMic;

window.fetchPsychology = fetchPsychology;
window.renderEmotionsDashboard = renderEmotionsDashboard;

window.loadSummary = loadSummary;
window.loadMoodHistory = loadMoodHistory;
window.loadDreams = loadDreams;
window.loadThoughts = loadThoughts;
window.loadSkills = loadSkills;
window.loadGoals = loadGoals;

window.resetLife = resetLife;
window.consolidate = consolidate;

window.toggleLive = toggleLive;
window.stopLive = stopLive;

window.startCamera = startCamera;
window.stopCamera = stopCamera;
window.captureVision = captureVision;

window.recordVoice = recordVoice;

window.checkInitialGreeting = checkInitialGreeting;
