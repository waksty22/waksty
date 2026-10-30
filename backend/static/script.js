'use strict';

/* ============================================================
   CHAPPIE V19.3 — INTERFACE COGNITIVE
   Conversation • Voix • Vision • Mémoire • Émotions
   Gemini Live • Compétences • Objectifs • Profils vocaux
   Compatible avec backend/server.py V19.3 fourni.
   ============================================================ */

/* 1. ÉTAT GLOBAL */
let recognition = null;
let speakingAudio = null;
let speakingAudioUrl = null;
let speechGeneration = 0;
let psychologyInterval = null;
let greetingInProgress = false;
let messageBusy = false;
let visionBusy = false;
let cameraStarting = false;
let cameraStream = null;
let visionInterval = null;
let liveSocket = null;
let liveStream = null;
let liveCtx = null;
let liveProcessor = null;
let liveSource = null;
let liveSilentGain = null;
let liveNextTime = 0;
let liveActive = false;
let liveAudioSources = new Set();
let voiceRecording = false;

const $ = id => document.getElementById(id);
const CREATOR_ID = 'creator';
const DEFAULT_VOICE = 'fr-FR-HenriNeural';
const LIVE_INPUT_RATE = 16000;
const LIVE_OUTPUT_RATE = 24000;

/* 2. OUTILS */
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
  return (($('token')?.value || $('tokenMobile')?.value || '')).trim();
}
function headers(extra = {}) {
  const token = getToken();
  return {
    ...(token ? { Authorization: 'Bearer ' + token } : {}),
    ...extra
  };
}
function requireToken() {
  if (getToken()) return true;
  setStatus('Saisis ton jeton API avant de continuer.');
  return false;
}
async function readResponse(response) {
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) {
    try { return await response.json(); } catch (_) { return {}; }
  }
  const body = await response.text();
  return body ? { detail: body } : {};
}
async function apiRequest(url, options = {}) {
  const requestHeaders = {
    ...headers(),
    ...(options.headers || {})
  };
  // Ne pas forcer application/json pour les corps binaires/FormData.
  if (options.body instanceof Blob || options.body instanceof FormData) {
    delete requestHeaders['Content-Type'];
  } else if (options.body && !requestHeaders['Content-Type']) {
    requestHeaders['Content-Type'] = 'application/json';
  }
  const response = await fetch(url, { ...options, headers: requestHeaders });
  const data = await readResponse(response);
  if (!response.ok) {
    const detail = data.detail || data.message || data.error || `Erreur HTTP ${response.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}
function jsonBody(value) { return JSON.stringify(value); }
function formatDate(value) {
  if (!value) return 'Date inconnue';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('fr-FR');
}
function formatTime(value) {
  if (!value) return '--:--';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}
function setOutput(message) { setText('out', message); }

/* 3. AFFICHAGE DES ÉMOTIONS SIMULÉES */
function renderEmotionsDashboard(psy, lastEvent = null) {
  if (!psy || typeof psy !== 'object') return;
  let container = $('state');
  if (!container) return;
  if (container.tagName === 'PRE') {
    const replacement = document.createElement('div');
    replacement.id = 'state';
    container.replaceWith(replacement);
    container = replacement;
  }
  const metrics = [
    ['⚡ Énergie', 'energy', '#10b981'],
    ['😊 Joie', 'joy', '#f59e0b'],
    ['🧐 Curiosité', 'curiosity', '#3b82f6'],
    ['😰 Peur / Inquiétude', 'fear', '#ef4444'],
    ['😤 Frustration', 'frustration', '#8b5cf6'],
    ['😢 Tristesse', 'sadness', '#64748b']
  ];
  const panel = document.createElement('div');
  Object.assign(panel.style, {
    display: 'flex', flexDirection: 'column', gap: '12px',
    background: '#0b1525', padding: '14px', borderRadius: '12px',
    border: '1px solid #20334c', color: '#fff'
  });
  for (const [labelText, key, baseColor] of metrics) {
    const raw = Number(psy[key] ?? 50);
    const value = Math.max(0, Math.min(100, Number.isFinite(raw) ? Math.round(raw) : 50));
    const item = document.createElement('div');
    Object.assign(item.style, { display: 'flex', flexDirection: 'column', gap: '5px' });
    const row = document.createElement('div');
    Object.assign(row.style, { display: 'flex', justifyContent: 'space-between', gap: '8px', fontSize: '13px', color: '#aabbd0' });
    const label = document.createElement('span'); label.textContent = labelText;
    const number = document.createElement('span'); number.textContent = `${value}%`;
    number.style.cssText = 'font-weight:700;color:#fff';
    row.append(label, number);
    const track = document.createElement('div');
    track.style.cssText = 'width:100%;height:9px;background:#131f31;border:1px solid #2b3b52;border-radius:6px;overflow:hidden';
    const bar = document.createElement('div');
    Object.assign(bar.style, { width: `${value}%`, height: '100%', background: key === 'energy' && value < 25 ? '#ef4444' : baseColor, borderRadius: '6px', transition: 'width .4s ease' });
    track.appendChild(bar); item.append(row, track); panel.appendChild(item);
  }
  if (lastEvent) {
    const eventBox = document.createElement('div');
    eventBox.style.cssText = 'margin-top:4px;padding-top:10px;border-top:1px solid #2b3b52;font-size:13px;color:#9de4f5;overflow-wrap:anywhere';
    const strong = document.createElement('strong'); strong.textContent = '🧠 Dernier événement : ';
    const span = document.createElement('span'); span.textContent = String(lastEvent);
    eventBox.append(strong, span); panel.appendChild(eventBox);
  }
  container.replaceChildren(panel);
}
async function fetchPsychology() {
  if (!getToken()) return;
  try {
    // Route serveur : GET /api/emotions/{user_id}
    const data = await apiRequest(`/api/emotions/${encodeURIComponent(CREATOR_ID)}`);
    if (data.psychology) renderEmotionsDashboard(data.psychology);
  } catch (error) { console.warn('Émotions :', error.message); }
}
function startPsychologyPolling() {
  if (psychologyInterval) clearInterval(psychologyInterval);
  psychologyInterval = setInterval(() => {
    if (document.visibilityState === 'visible') fetchPsychology();
  }, 30000);
}

/* 4. PREMIER RÉVEIL */
async function checkInitialGreeting() {
  const output = $('out');
  if (!output || !getToken() || greetingInProgress) return;
  const current = output.textContent.trim();
  if (!(current === '' || current.includes('En attente de ton message'))) return;
  greetingInProgress = true;
  setStatus('Chappie s’éveille…');
  try {
    const data = await apiRequest('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: jsonBody({ user_id: CREATOR_ID, message: '[Système : Si tu es en phase de premier réveil, prends l’initiative de parler. Utilise des phrases courtes, simples et adaptées à ton niveau de langage. Ne prétends pas posséder des expériences que tu n’as pas vécues.]' })
    });
    if (data.reply) {
      setOutput(data.reply);
      if (data.psychology) renderEmotionsDashboard(data.psychology);
      setStatus('Chappie a pris l’initiative !');
      await speak(data.reply);
    } else setStatus('Chappie est prêt.');
  } catch (error) {
    console.warn('Premier réveil :', error.message);
    setStatus('Interface prête. Vérifie le jeton et le serveur.');
  } finally { greetingInProgress = false; }
}

/* 5. CONVERSATION TEXTE */
async function sendMessage() {
  const input = $('msg');
  if (!input || messageBusy) return;
  const message = input.value.trim();
  if (!message) { setStatus('Écris un message avant de l’envoyer.'); return; }
  if (!requireToken()) return;
  messageBusy = true; setButtonDisabled('sendBtn', true);
  setStatus('Chappie réfléchit…'); setOutput('Chappie réfléchit…');
  try {
    const data = await apiRequest('/api/chat', {
      method: 'POST', body: jsonBody({ user_id: CREATOR_ID, message })
    });
    if (typeof data.reply !== 'string') throw new Error('La réponse du serveur ne contient pas de texte.');
    setOutput(data.reply);
    if (data.psychology) renderEmotionsDashboard(data.psychology);
    input.value = ''; setStatus('Réponse reçue.');
    await speak(data.reply);
  } catch (error) {
    setOutput('Erreur : ' + error.message);
    setStatus('Vérifie le jeton, la connexion et la configuration Gemini.');
  } finally { messageBusy = false; setButtonDisabled('sendBtn', false); }
}

/* 6. SYNTHÈSE VOCALE */
async function speak(text) {
  if (typeof text !== 'string' || !text.trim()) return;
  if (!requireToken()) return;
  const generation = ++speechGeneration;
  if (speakingAudio) {
    speakingAudio.pause(); speakingAudio.onended = null; speakingAudio.onerror = null; speakingAudio = null;
  }
  if (speakingAudioUrl) { URL.revokeObjectURL(speakingAudioUrl); speakingAudioUrl = null; }
  try {
    const response = await fetch('/api/speak', {
      method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' },
      body: jsonBody({ text, voice: DEFAULT_VOICE })
    });
    if (!response.ok) {
      const err = await readResponse(response);
      throw new Error(err.detail || 'La synthèse vocale est indisponible.');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('Le serveur a renvoyé un fichier audio vide.');
    if (generation !== speechGeneration) return;
    speakingAudioUrl = URL.createObjectURL(blob);
    const audio = new Audio(speakingAudioUrl);
    speakingAudio = audio;
    audio.onended = () => {
      if (generation !== speechGeneration) return;
      if (speakingAudioUrl) URL.revokeObjectURL(speakingAudioUrl);
      speakingAudioUrl = null; speakingAudio = null; setStatus('Prêt.');
    };
    audio.onerror = () => {
      if (generation !== speechGeneration) return;
      if (speakingAudioUrl) URL.revokeObjectURL(speakingAudioUrl);
      speakingAudioUrl = null; speakingAudio = null; setStatus('Erreur de lecture audio.');
    };
    setStatus('Lecture vocale en cours…');
    await audio.play();
  } catch (error) {
    if (generation !== speechGeneration) return;
    console.warn('Synthèse vocale :', error.message);
    setStatus('Réponse écrite prête ; lecture vocale indisponible.');
  }
}
function stopSpeech() {
  speechGeneration++;
  if (speakingAudio) {
    speakingAudio.pause(); try { speakingAudio.currentTime = 0; } catch (_) {}
    speakingAudio.onended = null; speakingAudio.onerror = null; speakingAudio = null;
  }
  if (speakingAudioUrl) { URL.revokeObjectURL(speakingAudioUrl); speakingAudioUrl = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  setStatus('Lecture arrêtée.');
}

/* 7. DICTÉE VOCALE */
function toggleMic() {
  const button = $('micBtn');
  const SpeechAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechAPI) { setStatus('La dictée nécessite un navigateur compatible, par exemple Chrome.'); return; }
  if (recognition) { try { recognition.stop(); } catch (_) {} return; }
  try {
    const instance = new SpeechAPI(); recognition = instance;
    instance.lang = 'fr-FR'; instance.interimResults = true; instance.continuous = false; instance.maxAlternatives = 1;
    instance.onresult = event => {
      let transcript = '';
      for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript;
      if ($('msg')) $('msg').value = transcript;
    };
    instance.onerror = event => setStatus('Dictée vocale : ' + event.error);
    instance.onend = () => {
      if (recognition === instance) recognition = null;
      if (button) button.textContent = '🎙️ Dicter';
      setStatus('Dictée terminée. Vérifie le texte puis envoie-le.');
    };
    if (button) button.textContent = '⏹️ Arrêter dictée';
    setStatus('Je t’écoute…'); instance.start();
  } catch (error) {
    recognition = null; if (button) button.textContent = '🎙️ Dicter';
    setStatus('Impossible de démarrer la dictée : ' + error.message);
  }
}

/* 8. MÉMOIRE, HISTORIQUE ET DONNÉES COGNITIVES */
async function loadSummary() {
  try { const d = await apiRequest('/api/memory/summary'); setText('summary', d.summary || 'Aucun résumé enregistré pour le moment.'); }
  catch (e) { setText('summary', 'Erreur de chargement : ' + e.message); }
}
async function loadMoodHistory() {
  try {
    const d = await apiRequest('/api/mood/history?limit=10');
    if (!Array.isArray(d.events)) throw new Error('Format de réponse inattendu.');
    if (!d.events.length) { setText('summary', 'Aucun événement d’humeur enregistré.'); return; }
    let out = '📜 Historique des 10 dernières humeurs\n\n';
    d.events.forEach(e => {
      const v = Number(e.valence); const sign = v > 0 ? '+' : '';
      out += `• [${formatTime(e.created_at)}] ${e.event || 'Événement'} (Valence : ${Number.isFinite(v) ? sign + v : '—'})\n`;
    });
    setText('summary', out);
  } catch (e) { setText('summary', 'Erreur d’historique : ' + e.message); }
}
async function loadDreams() {
  try {
    const d = await apiRequest(`/api/dreams/${encodeURIComponent(CREATOR_ID)}`);
    if (!Array.isArray(d.dreams)) throw new Error('Format de réponse inattendu.');
    if (!d.dreams.length) { setText('summary', 'Aucun rêve simulé enregistré.'); return; }
    let out = '🌙 Derniers rêves simulés de Chappie\n\n';
    d.dreams.forEach(x => { out += `• [${formatDate(x.created_at)}]\n  ${x.content || 'Contenu indisponible'}\n\n`; });
    setText('summary', out);
  } catch (e) { setText('summary', 'Erreur de chargement des rêves : ' + e.message); }
}
async function loadThoughts() {
  try {
    const d = await apiRequest(`/api/thoughts/${encodeURIComponent(CREATOR_ID)}`);
    if (!Array.isArray(d.thoughts)) throw new Error('Format de réponse inattendu.');
    if (!d.thoughts.length) { setText('summary', 'Aucune pensée métacognitive enregistrée.'); return; }
    let out = '🧠 Dernières pensées de Chappie\n\n';
    d.thoughts.forEach(x => { out += `• [${formatDate(x.created_at)}]\n  ${x.content || 'Contenu indisponible'}\n\n`; });
    setText('summary', out);
  } catch (e) { setText('summary', 'Erreur de chargement des pensées : ' + e.message); }
}
async function loadSkills() {
  try {
    const d = await apiRequest(`/api/skills/${encodeURIComponent(CREATOR_ID)}`);
    if (!Array.isArray(d.skills)) throw new Error('Format de réponse inattendu.');
    if (!d.skills.length) { setText('summary', 'Aucune compétence enregistrée.'); return; }
    const maturity = Number(d.cognitive_profile?.global_maturity ?? d.average_level ?? 1);
    let out = `🎓 Écosystème cognitif de Chappie\nMaturité globale : ${maturity.toFixed(1)}/10\n\n`;
    d.skills.forEach(s => {
      const level = Number(s.level ?? 0), xp = Number(s.xp ?? 0);
      out += `🔹 ${(s.skill_name || s.name || 'Compétence').toUpperCase()}\n   Niveau : ${Math.round(level)}\n   XP : ${Math.round(xp)} — ${Math.round(Math.max(0, Math.min(100, xp % 100)))}% du prochain palier\n   Preuve : ${s.evidence || 'Aucune'}\n\n`;
    });
    const b = d.cognitive_profile?.behavior;
    if (b) out += `⚙️ Profil comportemental\n• Complexité : ${b.response_complexity ?? '—'}\n• Vocabulaire : ${b.vocabulary_richness ?? '—'}\n• Humour : ${b.humor_description ?? '—'}\n• Incertitude : ${b.uncertainty_handling ?? '—'}\n`;
    setText('summary', out);
  } catch (e) { setText('summary', 'Erreur de chargement des compétences : ' + e.message); }
}
async function loadGoals() {
  try {
    const d = await apiRequest('/api/goals');
    if (!Array.isArray(d.goals)) throw new Error('Format de réponse inattendu.');
    if (!d.goals.length) { setText('summary', 'Aucun objectif actif pour le moment.'); return; }
    let out = '🎯 Objectifs de Chappie\n\n';
    d.goals.forEach(g => {
      const progress = Math.max(0, Math.min(100, Math.round(Number(g.progress) || 0)));
      out += `📌 ${g.title || 'Objectif sans titre'} (${progress}%)\n`;
      if (Array.isArray(g.steps)) g.steps.forEach(s => { out += `   ${s.status === 'completed' ? '✅' : '⏳'} ${s.description || 'Étape sans description'}\n`; });
      out += '\n';
    });
    setText('summary', out);
  } catch (e) { setText('summary', 'Erreur de chargement des objectifs : ' + e.message); }
}
async function consolidate() {
  if (!requireToken()) return;
  setStatus('Consolidation de la mémoire en cours…');
  try {
    const d = await apiRequest('/api/memory/consolidate', { method: 'POST' });
    setText('summary', d.summary || d.message || 'Consolidation terminée.');
    setStatus('Mémoire consolidée.');
  } catch (e) { setText('summary', 'Erreur : ' + e.message); setStatus('Consolidation impossible.'); }
}
async function resetLife() {
  if (!requireToken()) return;
  const ok = window.confirm('⚠️ Réinitialiser Chappie à zéro ? Cette action peut effacer ses souvenirs, son historique et ses données. Vérifie que tu disposes d’une sauvegarde.');
  if (!ok) return;
  setStatus('Réinitialisation de Chappie en cours…');
  try {
    const d = await apiRequest('/api/reset-life', { method: 'POST' });
    setText('summary', d.message || 'Réinitialisation demandée.');
    setOutput('Bip… Où suis-je ? Bonjour… c’est quoi cet endroit ?');
    setStatus('Réinitialisation terminée.'); await fetchPsychology();
  } catch (e) { setStatus('Erreur de réinitialisation : ' + e.message); }
}

/* 9. CONVERSION AUDIO / PCM */
function bytesToBase64(bytes) {
  let binary = ''; const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + step, bytes.length)));
  return btoa(binary);
}
function base64ToBytes(value) {
  const raw = atob(value); const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}
function floatToPcm16Base64(float32) {
  const buffer = new ArrayBuffer(float32.length * 2); const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 32768 : s * 32767, true);
  }
  return bytesToBase64(new Uint8Array(buffer));
}
function resample(input, fromRate, toRate) {
  if (!input?.length || !fromRate || !toRate) return new Float32Array(0);
  if (fromRate === toRate) return new Float32Array(input);
  const ratio = fromRate / toRate; const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0; for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / (end - start);
  }
  return out;
}

/* 10. GEMINI LIVE — TRANSMISSION DES IMAGES */
function startLiveVision() {
  stopLiveVision();
  const video = $('camera');
  if (!video || !cameraStream) return;
  const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 360;
  const ctx = canvas.getContext('2d'); if (!ctx) return;
  visionInterval = setInterval(() => {
    if (!liveActive || !liveSocket || liveSocket.readyState !== WebSocket.OPEN || !video.videoWidth || !video.videoHeight) return;
    try {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/jpeg', 0.4).split(',')[1];
      if (data) liveSocket.send(JSON.stringify({ video: { mimeType: 'image/jpeg', data } }));
    } catch (e) { console.warn('Image Live non envoyée :', e.message); }
  }, 1800);
}
function stopLiveVision() { if (visionInterval) { clearInterval(visionInterval); visionInterval = null; } }

/* 11. GEMINI LIVE — CONVERSATION TEMPS RÉEL */
async function toggleLive() {
  if (liveActive || liveSocket) { stopLive(); return; }
  if (!requireToken()) { setText('liveStatus', 'Saisis ton jeton API avant de démarrer.'); return; }
  if (!navigator.mediaDevices?.getUserMedia) { setText('liveStatus', 'Le microphone nécessite HTTPS et un navigateur compatible.'); return; }
  try {
    setText('liveStatus', 'Demande d’accès au microphone…');
    liveStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error('AudioContext indisponible dans ce navigateur.');
    liveCtx = new AudioContextClass(); await liveCtx.resume();
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${scheme}//${location.host}/ws/live?token=${encodeURIComponent(getToken())}`);
    liveSocket = socket;
    socket.onopen = () => {
      if (socket !== liveSocket) return;
      liveActive = true;
      if ($('liveBtn')) $('liveBtn').textContent = '⏹ Arrêter la conversation';
      setText('liveStatus', 'WebSocket connectée. Initialisation audio…');
      try {
        liveSource = liveCtx.createMediaStreamSource(liveStream);
        liveProcessor = liveCtx.createScriptProcessor(2048, 1, 1);
        liveSilentGain = liveCtx.createGain(); liveSilentGain.gain.value = 0;
        liveProcessor.onaudioprocess = event => {
          if (!liveActive || socket !== liveSocket || socket.readyState !== WebSocket.OPEN) return;
          const pcm = resample(event.inputBuffer.getChannelData(0), liveCtx.sampleRate, LIVE_INPUT_RATE);
          if (!pcm.length) return;
          try { socket.send(JSON.stringify({ audio: floatToPcm16Base64(pcm) })); }
          catch (e) { console.warn('Envoi micro :', e.message); }
        };
        liveSource.connect(liveProcessor); liveProcessor.connect(liveSilentGain); liveSilentGain.connect(liveCtx.destination);
        if (cameraStream) startLiveVision();
        setText('liveStatus', 'Micro actif. Chappie se connecte à Gemini Live…');
      } catch (e) { setText('liveStatus', 'Erreur de préparation audio : ' + e.message); stopLive(); }
    };
    socket.onmessage = event => {
      if (socket !== liveSocket) return;
      let data; try { data = JSON.parse(event.data); } catch (_) { return; }
      if (data.status) setText('liveStatus', data.status);
      if (data.error) setText('liveStatus', 'Erreur : ' + data.error);
      if (data.interrupt) {
        for (const source of liveAudioSources) { try { source.stop(); } catch (_) {} }
        liveAudioSources.clear(); liveNextTime = liveCtx ? liveCtx.currentTime : 0;
      }
      // Le serveur transmet inputTranscription sous user_text.
      if (data.user_text) appendLiveTranscript('Toi : ', data.user_text);
      if (data.text) {
        appendLiveTranscript('Chappie : ', data.text);
        const output = $('out'); if (output) output.textContent = (output.textContent.startsWith('En attente') ? '' : output.textContent + '\n') + 'Chappie : ' + data.text;
      }
      if (data.audio) playLiveAudio(data.audio, data.sample_rate || LIVE_OUTPUT_RATE);
      if (data.psychology) renderEmotionsDashboard(data.psychology);
    };
    socket.onerror = () => { if (socket === liveSocket) setText('liveStatus', 'Erreur WebSocket. Vérifie le serveur, le jeton et les logs Render.'); };
    socket.onclose = () => {
      if (socket !== liveSocket) return;
      stopLive(false); setText('liveStatus', 'Session Live terminée.');
    };
  } catch (e) {
    setText('liveStatus', 'Impossible de démarrer : ' + e.message); stopLive();
  }
}
function appendLiveTranscript(prefix, value) {
  const transcript = $('liveTranscript');
  if (transcript) {
    const line = `${prefix}${String(value).trim()}`;
    transcript.textContent = (transcript.textContent ? transcript.textContent + '\n' : '') + line;
    transcript.scrollTop = transcript.scrollHeight;
  }
}
function playLiveAudio(encoded, rate = LIVE_OUTPUT_RATE) {
  if (!liveCtx || !encoded) return;
  try {
    const bytes = base64ToBytes(encoded); if (bytes.length < 2) return;
    const count = Math.floor(bytes.length / 2);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const samples = new Float32Array(count);
    for (let i = 0; i < count; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
    const sampleRate = Number(rate) || LIVE_OUTPUT_RATE;
    const buffer = liveCtx.createBuffer(1, samples.length, sampleRate); buffer.copyToChannel(samples, 0);
    const source = liveCtx.createBufferSource(); source.buffer = buffer; source.connect(liveCtx.destination);
    liveAudioSources.add(source); source.onended = () => liveAudioSources.delete(source);
    const now = liveCtx.currentTime; if (liveNextTime < now) liveNextTime = now + 0.08;
    source.start(liveNextTime); liveNextTime += buffer.duration;
  } catch (e) { console.error('Lecture audio Live :', e); }
}
function stopLive(closeSocket = true) {
  liveActive = false; stopLiveVision();
  const socket = liveSocket; liveSocket = null;
  if (socket && closeSocket) {
    try { socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null; if (socket.readyState < WebSocket.CLOSING) socket.close(1000, 'Arrêt demandé par utilisateur'); } catch (_) {}
  }
  if (liveProcessor) { try { liveProcessor.disconnect(); liveProcessor.onaudioprocess = null; } catch (_) {} }
  if (liveSource) { try { liveSource.disconnect(); } catch (_) {} }
  if (liveSilentGain) { try { liveSilentGain.disconnect(); } catch (_) {} }
  if (liveStream) liveStream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} });
  for (const source of liveAudioSources) { try { source.stop(); } catch (_) {} }
  liveAudioSources.clear();
  if (liveCtx && liveCtx.state !== 'closed') { try { liveCtx.close(); } catch (_) {} }
  liveStream = null; liveCtx = null; liveProcessor = null; liveSource = null; liveSilentGain = null; liveNextTime = 0;
  if ($('liveBtn')) $('liveBtn').textContent = '▶ Démarrer la conversation live';
  if (closeSocket) setText('liveStatus', 'Conversation arrêtée.');
}

/* 12. CAMÉRA ET ANALYSE VISUELLE */
async function startCamera() {
  if (cameraStream || cameraStarting) return;
  if (!navigator.mediaDevices?.getUserMedia) { setText('visionOut', 'La caméra nécessite HTTPS ou un environnement local sécurisé.'); return; }
  cameraStarting = true;
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    const video = $('camera');
    if (!video) throw new Error('Élément vidéo #camera introuvable dans le HTML.');
    video.srcObject = cameraStream; video.playsInline = true; video.muted = true;
    try { await video.play(); } catch (_) {}
    setText('visionOut', 'Caméra active. Chappie peut analyser une image.');
    if (liveActive && liveSocket) startLiveVision();
  } catch (e) {
    if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null; setText('visionOut', 'Accès caméra impossible : ' + e.message);
  } finally { cameraStarting = false; }
}
function stopCamera() {
  stopLiveVision();
  if (cameraStream) cameraStream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} });
  cameraStream = null;
  const video = $('camera'); if (video) { try { video.pause(); } catch (_) {} video.srcObject = null; }
  setText('visionOut', 'Caméra inactive.');
}
async function captureVision() {
  if (visionBusy) return;
  if (!requireToken()) return;
  const video = $('camera');
  if (!cameraStream || !video || !video.videoWidth || !video.videoHeight) { setText('visionOut', 'Active la caméra et attends que l’image apparaisse.'); return; }
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 960 / video.videoWidth, 960 / video.videoHeight);
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  const ctx = canvas.getContext('2d'); if (!ctx) { setText('visionOut', 'Impossible de préparer l’image.'); return; }
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  let imageData; try { imageData = canvas.toDataURL('image/jpeg', 0.65); } catch (_) { setText('visionOut', 'Impossible de capturer l’image.'); return; }
  visionBusy = true; setText('visionOut', 'Chappie observe l’image…');
  try {
    const result = await apiRequest('/api/vision/analyze', {
      method: 'POST', body: jsonBody({ image_data_url: imageData, prompt: 'Décris ce que tu vois. Distingue les éléments certains des suppositions. Décris les objets, les couleurs, les positions et le contexte. Si une personne est visible, décris son apparence sans chercher à déterminer son identité.' })
    });
    const description = result.description;
    if (!description) throw new Error('Aucune description reçue du serveur.');
    setText('visionOut', 'Ce que Chappie voit :\n' + description + '\n\nChappie prépare sa réponse…');
    const chat = await apiRequest('/api/chat', { method: 'POST', body: jsonBody({ user_id: CREATOR_ID, message: 'Tu viens d’analyser une image avec ta caméra. Voici la description obtenue :\n' + description + '\nRéagis naturellement à ce que tu observes et explique-moi ce que tu en comprends.' }) });
    if (!chat.reply) throw new Error('Chappie n’a pas renvoyé de réponse.');
    setText('visionOut', 'Ce que Chappie voit :\n' + description); setOutput(chat.reply);
    if (chat.psychology) renderEmotionsDashboard(chat.psychology);
    setStatus('Image analysée et réponse reçue.'); await speak(chat.reply);
  } catch (e) { setText('visionOut', 'Erreur caméra : ' + e.message); setStatus('Vérifie le jeton et la configuration du serveur.'); }
  finally { visionBusy = false; }
}

/* 13. ENREGISTREMENT WAV POUR LES PROFILS VOCAUX */
function wavBlob(floatSamples, sampleRate) {
  const targetRate = 16000; const samples = resample(floatSamples, sampleRate, targetRate);
  const buffer = new ArrayBuffer(44 + samples.length * 2); const view = new DataView(buffer);
  const write = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  write(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); write(8, 'WAVE'); write(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const s = Math.max(-1, Math.min(1, samples[i])); view.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true); }
  return new Blob([buffer], { type: 'audio/wav' });
}
async function recordVoice(mode) {
  if (!requireToken()) return;
  if (voiceRecording) { setText('voiceStatus', 'Un enregistrement vocal est déjà en cours.'); return; }
  if (!navigator.mediaDevices?.getUserMedia) { setText('voiceStatus', 'Microphone non disponible.'); return; }
  const name = $('voiceName')?.value.trim() || '';
  if (mode === 'enroll' && !name) { setText('voiceStatus', 'Saisis un nom de profil.'); return; }
  if (!['enroll', 'identify'].includes(mode)) { setText('voiceStatus', 'Mode vocal inconnu.'); return; }
  voiceRecording = true;
  let stream = null, context = null, source = null, processor = null, gain = null;
  const chunks = [];
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    context = new AudioContextClass(); await context.resume();
    const sampleRate = context.sampleRate; source = context.createMediaStreamSource(stream);
    processor = context.createScriptProcessor(4096, 1, 1); gain = context.createGain(); gain.gain.value = 0;
    processor.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(processor); processor.connect(gain); gain.connect(context.destination);
    const seconds = mode === 'enroll' ? 8 : 5;
    setText('voiceStatus', `Enregistrement ${mode === 'enroll' ? 'du profil' : 'de comparaison'}… parle naturellement pendant ${seconds} secondes.`);
    await new Promise(resolve => setTimeout(resolve, seconds * 1000));
    const total = chunks.reduce((n, x) => n + x.length, 0);
    if (!total) throw new Error('Aucun son enregistré.');
    const samples = new Float32Array(total); let offset = 0;
    for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
    const blob = wavBlob(samples, sampleRate);
    const endpoint = mode === 'enroll' ? '/api/voice-profiles/' + encodeURIComponent(name) : '/api/voice-profiles-identify';
    const response = await fetch(endpoint, { method: 'POST', headers: headers({ 'Content-Type': 'audio/wav' }), body: blob });
    const data = await readResponse(response);
    if (!response.ok) throw new Error(data.detail || 'Erreur lors du traitement du profil vocal.');
    if (mode === 'enroll') setText('voiceStatus', 'Profil enregistré : ' + (data.profile_name || name));
    else setText('voiceStatus', `Résultat : ${data.profile_name || 'Personne non reconnue'} (score ${data.score ?? '—'})`);
  } catch (e) { setText('voiceStatus', 'Profils vocaux : ' + e.message); }
  finally {
    if (processor) { try { processor.disconnect(); } catch (_) {} }
    if (source) { try { source.disconnect(); } catch (_) {} }
    if (gain) { try { gain.disconnect(); } catch (_) {} }
    if (stream) stream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} });
    if (context && context.state !== 'closed') { try { await context.close(); } catch (_) {} }
    voiceRecording = false;
  }
}

/* 14. INITIALISATION ET EXPORT DES FONCTIONS HTML */
function initializeChappie() {
  setStatus('Interface chargée. Jeton requis pour les fonctions protégées.');
  console.info('Chappie V19.3 : interface prête.');
  const input = $('msg');
  if (input) input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); }
  });
  const tokenInput = $('token');
  const tokenMobile = $('tokenMobile');
  const onTokenChange = () => {
    if (getToken()) { fetchPsychology(); checkInitialGreeting(); }
  };
  if (tokenInput) { tokenInput.addEventListener('change', onTokenChange); tokenInput.addEventListener('input', () => { if (tokenMobile && tokenMobile.value !== tokenInput.value) tokenMobile.value = tokenInput.value; }); }
  if (tokenMobile) { tokenMobile.addEventListener('change', onTokenChange); tokenMobile.addEventListener('input', () => { if (tokenInput && tokenInput.value !== tokenMobile.value) tokenInput.value = tokenMobile.value; }); }
  if (getToken()) { fetchPsychology(); setTimeout(checkInitialGreeting, 1000); }
  startPsychologyPolling();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeChappie, { once: true });
else initializeChappie();

window.addEventListener('pagehide', () => {
  stopLive(); stopLiveVision();
  if (recognition) { try { recognition.abort(); } catch (_) {} recognition = null; }
  if (speakingAudio) { speakingAudio.pause(); speakingAudio = null; }
  if (speakingAudioUrl) { URL.revokeObjectURL(speakingAudioUrl); speakingAudioUrl = null; }
  if (cameraStream) { cameraStream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} }); cameraStream = null; }
  if (psychologyInterval) { clearInterval(psychologyInterval); psychologyInterval = null; }
});

// Fonctions appelées directement depuis les boutons et attributs HTML.
Object.assign(window, {
  sendMessage, speak, stopSpeech, toggleMic,
  fetchPsychology, renderEmotionsDashboard,
  loadSummary, loadMoodHistory, loadDreams, loadThoughts, loadSkills, loadGoals,
  resetLife, consolidate, toggleLive, stopLive,
  startCamera, stopCamera, captureVision, recordVoice,
  checkInitialGreeting
});
