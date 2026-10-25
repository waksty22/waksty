/* Chappie — Interface Front-End Unifiée & Ultime */
'use strict';

const $ = id => document.getElementById(id);
const USER_ID = 'creator';
let recognition = null;
let cameraStream = null;
let activeAudio = null;

// --- Gestion des en-têtes d'authentification ---
function headers(json = true) {
  const tokenField = $('token');
  const token = tokenField ? tokenField.value.trim() : '';
  const h = {};
  if (json) h['Content-Type'] = 'application/json';
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

function setStatus(s) {
  const st = $('status');
  if (st) st.textContent = s;
}

// --- Requête API centralisée ---
async function api(path, options = {}) {
  const response = await fetch(path, { 
    ...options, 
    headers: { ...headers(options.json !== false), ...(options.headers || {}) } 
  });
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(typeof data === 'object' ? (data.detail || `Erreur HTTP ${response.status}`) : `Erreur HTTP ${response.status}`);
  return data;
}

function jsonOptions(method, body) { 
  return { method, body: JSON.stringify(body) }; 
}

// --- Rendu visuel du tableau de bord émotionnel ---
function renderEmotionsDashboard(psy, lastEvent = null) {
  const container = $('state');
  if (!container || !psy) return;

  if (container.tagName === 'PRE') {
    const div = document.createElement('div');
    div.id = 'state';
    container.parentNode.replaceChild(div, container);
  }

  const stateEl = $('state');
  const metrics = [
    { label: '⚡ Énergie', key: 'energy', color: '#10b981' },
    { label: '😊 Joie', key: 'joy', color: '#f59e0b' },
    { label: '🧐 Curiosité', key: 'curiosity', color: '#3b82f6' },
    { label: '😰 Peur / Inquiétude', key: 'fear', color: '#ef4444' },
    { label: '😤 Frustration', key: 'frustration', color: '#8b5cf6' },
    { label: '😢 Tristesse', key: 'sadness', color: '#64748b' }
  ];

  let html = '<div style="display: flex; flex-direction: column; gap: 10px; background: #0b1525; padding: 14px; border-radius: 10px;">';
  
  metrics.forEach(m => {
    const val = Math.max(0, Math.min(100, Math.round(psy[m.key] ?? 50)));
    let barColor = m.color;
    if (m.key === 'energy' && val < 25) barColor = '#ef4444';

    html += `
      <div style="display: flex; flex-direction: column; gap: 4px;">
        <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #aabbd0;">
          <span>${m.label}</span>
          <span style="font-weight: bold; color: #fff;">${val}%</span>
        </div>
        <div style="width: 100%; background: #131f31; height: 10px; border-radius: 5px; overflow: hidden; border: 1px solid #2b3b52;">
          <div style="width: ${val}%; background: ${barColor}; height: 100%; transition: width 0.5s ease-in-out, background-color 0.5s ease-in-out;"></div>
        </div>
      </div>
    `;
  });

  if (lastEvent) {
    html += `
      <div style="margin-top: 6px; padding-top: 8px; border-top: 1px solid #2b3b52; font-size: 0.8rem; color: #9de4f5;">
        🧠 <strong>Dernier événement :</strong> ${lastEvent}
      </div>
    `;
  }

  html += '</div>';
  stateEl.innerHTML = html;
}

// --- Polling régulier de l'état psychologique ---
let psychologyInterval = null;
async function fetchPsychology() {
  const tokenField = $('token');
  const token = tokenField ? tokenField.value.trim() : '';
  if (!token) return;

  try {
    const d = await api(`/api/emotions/${USER_ID}`, { method: 'GET' });
    if (d.psychology) renderEmotionsDashboard(d.psychology);
  } catch (e) {}
}

if (psychologyInterval) clearInterval(psychologyInterval);
psychologyInterval = setInterval(fetchPsychology, 30000);

// --- Envoi de message standard ---
async function sendMessage() {
  const msgInput = $('msg');
  const message = msgInput.value.trim();
  if (!message) return;
  
  const btn = $('sendBtn');
  btn.disabled = true;
  setStatus('Chappie réfléchit...');
  $('out').textContent = 'Réflexion...';
  
  try {
    const d = await api('/api/chat', { ...jsonOptions('POST', { user_id: USER_ID, message }) });
    
    $('out').textContent = d.reply;
    if (d.psychology) renderEmotionsDashboard(d.psychology);
    msgInput.value = '';
    setStatus('Réponse reçue.');
    await speak(d.reply);
  } catch (e) {
    $('out').textContent = 'Erreur : ' + e.message;
    setStatus('Vérifie le jeton, la connexion et la configuration Gemini.');
  } finally {
    btn.disabled = false;
  }
}

// --- Synthèse vocale standard ---
async function speak(text) {
  try {
    stopSpeech(false);
    const response = await fetch('/api/speak', {
      method: 'POST', 
      headers: headers(), 
      body: JSON.stringify({ text, voice: 'fr-FR-HenriNeural' })
    });
    if (!response.ok) {
      setStatus('Réponse écrite prête ; synthèse vocale indisponible.');
      return;
    }
    
    const arrayBuffer = await response.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.playbackRate.value = 1.0;
    source.connect(audioCtx.destination);
    source.start(0);
    setStatus('Lecture vocale en cours...');

    source.onended = () => {
      setStatus('Prêt.');
      audioCtx.close();
    };
  } catch (e) {
    setStatus('Réponse écrite prête ; lecture vocale impossible dans ce navigateur.');
  }
}

function stopSpeech(showStatus = true) {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio = null;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (showStatus) setStatus('Lecture arrêtée.');
}

// --- Reconnaissance vocale (Dictée) ---
function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    setStatus('La dictée vocale nécessite un navigateur compatible (ex: Chrome).');
    return;
  }
  if (recognition) {
    recognition.stop();
    recognition = null;
    $('micBtn').textContent = '🎙️ Dicter';
    return;
  }
  recognition = new SR();
  recognition.lang = 'fr-FR';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onresult = e => {
    let text = '';
    for (let i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript;
    $('msg').value = text;
  };
  recognition.onerror = e => setStatus('Dictée : ' + e.error);
  recognition.onend = () => {
    $('micBtn').textContent = '🎙️ Dicter';
    recognition = null;
    setStatus('Dictée terminée.');
  };
  $('micBtn').textContent = '⏹️ Arrêter dictée';
  setStatus('Je t’écoute...');
  recognition.start();
}

// --- Panneaux de chargement (Mémoire, Humeur, Rêves, Pensées, Compétences) ---
async function loadSummary() {
  try {
    const d = await api('/api/memory/summary', { method: 'GET' });
    $('summary').textContent = d.summary || 'Aucun résumé enregistré.';
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement : ' + e.message;
  }
}

async function loadMoodHistory() {
  try {
    const d = await api('/api/mood/history?limit=10', { method: 'GET' });
    if (d.events && d.events.length > 0) {
      let text = "📜 Historique des 10 dernières humeurs :\n\n";
      d.events.forEach(e => {
        const date = new Date(e.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const valSign = e.valence > 0 ? '+' : '';
        text += `• [${date}] ${e.event} (Valence: ${valSign}${e.valence})\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Aucun événement d’humeur enregistré.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur : ' + e.message;
  }
}

async function loadDreams() {
  try {
    const d = await api(`/api/dreams/${USER_ID}`, { method: 'GET' });
    if (d.dreams && d.dreams.length > 0) {
      let text = "🌙 Derniers rêves simulés de Chappie :\n\n";
      d.dreams.forEach(dream => {
        const date = new Date(dream.created_at).toLocaleString('fr-FR');
        text += `• [${date}]\n  "${dream.content}"\n\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Aucun rêve simulé enregistré.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur : ' + e.message;
  }
}

async function loadThoughts() {
  try {
    const d = await api(`/api/thoughts/${USER_ID}`, { method: 'GET' });
    if (d.thoughts && d.thoughts.length > 0) {
      let text = "🧠 Dernières pensées et ruminations de Chappie :\n\n";
      d.thoughts.forEach(t => {
        const date = new Date(t.created_at).toLocaleString('fr-FR');
        text += `• [${date}]\n  "${t.content}"\n\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Aucune pensée métacognitive enregistrée.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur : ' + e.message;
  }
}

async function loadSkills() {
  try {
    const d = await api(`/api/skills/${USER_ID}`, { method: 'GET' });
    if (d.skills && d.skills.length > 0) {
      let text = `🎓 Arbre de Compétences de Chappie (Moyenne globale : ${(d.average_level || 1).toFixed(1)}/10) :\n\n`;
      d.skills.forEach(s => {
        text += `🔹 ${s.skill_name} : Niveau ${Math.round(s.level)} (XP: ${Math.round(s.xp)})\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Aucune compétence enregistrée.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur : ' + e.message;
  }
}

async function loadGoals() {
  try {
    const d = await api(`/api/goals?user_id=${USER_ID}`, { method: 'GET' });
    const root = $('goals') || $('summary');
    if (d.goals && d.goals.length > 0) {
      let text = "🎯 Objectifs actifs de Chappie :\n\n";
      d.goals.forEach(g => {
        text += `📌 ${g.title} (Progression : ${Math.round(g.progress)}%)\n`;
        if (g.steps && g.steps.length > 0) {
          g.steps.forEach(s => {
            const icon = s.status === 'completed' ? '✅' : '⏳';
            text += `   ${icon} ${s.description}\n`;
          });
        }
        text += '\n';
      });
      root.textContent = text;
    } else {
      root.textContent = 'Aucun objectif actif.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur : ' + e.message;
  }
}

async function consolidate() {
  try {
    const d = await api('/api/memory/consolidate', { method: 'POST' });
    $('summary').textContent = d.summary || 'Aucun échange à résumer.';
    setStatus('Mémoire consolidée.');
  } catch (e) {
    setStatus('Erreur de consolidation.');
  }
}

async function resetLife() {
  if (!confirm("⚠️ Es-tu sûr de vouloir effacer toute la mémoire et réinitialiser Chappie à zéro (Page Blanche) ?")) return;
  try {
    setStatus('Réinitialisation en cours...');
    const d = await api('/api/reset-life', { method: 'POST' });
    $('summary').textContent = "🐣 Chappie est né à nouveau (Stade 0). Tout est effacé !";
    $('out').textContent = "Bip... Où suis-je ? Bonjour...";
    setStatus('Chappie est un nouveau-né !');
    fetchPsychology();
  } catch (e) {
    setStatus('Erreur de réinitialisation : ' + e.message);
  }
}

// --- Gemini Live & Vision Temps Réel ---
let liveSocket = null, liveStream = null, liveCtx = null, liveProcessor = null, liveSource = null, liveNextTime = 0, liveActive = false, liveAudioSources = new Set();
let visionInterval = null;

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

function fromB64(s) {
  const raw = atob(s), a = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) a[i] = raw.charCodeAt(i);
  return a;
}

function pcm16Base64(float32) {
  const out = new ArrayBuffer(float32.length * 2), v = new DataView(out);
  for (let i = 0; i < float32.length; i++) {
    const x = Math.max(-1, Math.min(1, float32[i]));
    v.setInt16(i * 2, x < 0 ? x * 32768 : x * 32767, true);
  }
  return b64(new Uint8Array(out));
}

function resample(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate, len = Math.floor(input.length / ratio), out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0, n = 0;
    for (let j = start; j < end; j++) { sum += input[j]; n++; }
    out[i] = n ? sum / n : input[start] || 0;
  }
  return out;
}

function startLiveVision() {
  stopLiveVision();
  const video = $('camera');
  if (!video || !cameraStream) return;

  const canvas = document.createElement('canvas');
  canvas.width = 480;
  canvas.height = 360;
  const ctx = canvas.getContext('2d');

  visionInterval = setInterval(() => {
    if (!liveActive || !liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
    if (!video.videoWidth || !video.videoHeight) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const base64Image = canvas.toDataURL('image/jpeg', 0.4).split(',')[1];
    if (!base64Image) return;

    liveSocket.send(JSON.stringify({
      video: { mimeType: 'image/jpeg', data: base64Image }
    }));
  }, 1500);
}

function stopLiveVision() {
  if (visionInterval) {
    clearInterval(visionInterval);
    visionInterval = null;
  }
}

async function toggleLive() {
  if (liveActive) {
    stopLive();
    return;
  }

  const tokenField = $('token');
  const token = tokenField ? tokenField.value.trim() : '';
  if (!token) {
    $('liveStatus').textContent = 'Erreur : Saisis ton jeton API avant de démarrer le live.';
    return;
  }

  try {
    liveStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    liveCtx = new (window.AudioContext || window.webkitAudioContext)();
    await liveCtx.resume();
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    liveSocket = new WebSocket(proto + '//' + location.host + '/ws/live?token=' + encodeURIComponent(token));
    
    liveSocket.onopen = () => {
      liveActive = true;
      $('liveBtn').textContent = '⏸ Arrêter la conversation';
      $('liveStatus').textContent = 'Connexion à Gemini Live...';
      liveSource = liveCtx.createMediaStreamSource(liveStream);
      liveProcessor = liveCtx.createScriptProcessor(2048, 1, 1);
      liveProcessor.onaudioprocess = e => {
        if (!liveActive || !liveSocket || liveSocket.readyState !== WebSocket.OPEN) return;
        const input = e.inputBuffer.getChannelData(0), pcm = resample(input, liveCtx.sampleRate, 16000);
        liveSocket.send(JSON.stringify({ audio: pcm16Base64(pcm) }));
      };
      liveSource.connect(liveProcessor);
      liveProcessor.connect(liveCtx.destination);

      if (cameraStream) startLiveVision();
    };
    
    liveSocket.onmessage = async e => {
      let d;
      try { d = JSON.parse(e.data); } catch { return; }
      if (d.status) { $('liveStatus').textContent = d.status; return; }
      if (d.interrupt) {
        for (const a of liveAudioSources) { try { a.stop(); } catch {} }
        liveAudioSources.clear();
        liveNextTime = liveCtx ? liveCtx.currentTime : 0;
        $('out').textContent = 'Chappie : ';
      }
      if (d.text) { 
        const outEl = $('out');
        if (outEl.textContent.startsWith('En attente') || outEl.textContent === 'Chappie : ') {
          outEl.textContent = 'Chappie : ' + d.text;
        } else {
          outEl.textContent += d.text;
        }
      }
      if (d.audio) { 
        playLiveAudio(d.audio, d.sample_rate || 24000); 
      }
      if (d.error) { $('liveStatus').textContent = 'Erreur : ' + d.error; }
      if (d.psychology) renderEmotionsDashboard(d.psychology);
    };
    
    liveSocket.onerror = () => { $('liveStatus').textContent = 'Erreur WebSocket.'; };
    liveSocket.onclose = () => {
      if (liveActive) stopLive(false);
      $('liveStatus').textContent = 'Session terminée.';
    };
  } catch (e) {
    $('liveStatus').textContent = 'Impossible de démarrer : ' + e.message;
    stopLive();
  }
}

function playLiveAudio(encoded, rate) {
  if (!liveCtx) return;
  try {
    const bytes = fromB64(encoded);
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const f = new Float32Array(Math.floor(bytes.length / 2));
    
    for (let i = 0; i < f.length; i++) {
      f[i] = dv.getInt16(i * 2, true) / 32768;
    }

    const buf = liveCtx.createBuffer(1, f.length, rate || 24000);
    buf.copyToChannel(f, 0);
    
    const src = liveCtx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = 1.0;
    src.connect(liveCtx.destination);
    liveAudioSources.add(src);
    src.onended = () => liveAudioSources.delete(src);

    const now = liveCtx.currentTime;
    if (liveNextTime < now) liveNextTime = now + 0.15;
    src.start(liveNextTime);
    liveNextTime += buf.duration;
  } catch (e) {
    console.error("Erreur lecture audio live :", e);
  }
}

function stopLive(close = true) {
  liveActive = false;
  stopLiveVision();
  try { if (liveProcessor) { liveProcessor.disconnect(); liveProcessor.onaudioprocess = null; } } catch {}
  try { if (liveSource) liveSource.disconnect(); } catch {}
  try { if (liveStream) liveStream.getTracks().forEach(t => t.stop()); } catch {}
  try { if (liveSocket && close && liveSocket.readyState < 2) liveSocket.close(); } catch {}
  try { if (liveCtx) liveCtx.close(); } catch {}
  for (const a of liveAudioSources) { try { a.stop(); } catch {} }
  liveAudioSources.clear();
  liveSocket = null; liveStream = null; liveCtx = null; liveProcessor = null; liveSource = null; liveNextTime = 0;
  if ($('liveBtn')) $('liveBtn').textContent = '▶ Démarrer la conversation live';
}

// --- Gestion Caméra Standard ---
async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    $('camera').srcObject = cameraStream;
    $('visionOut').textContent = 'Caméra active.';
    if (liveActive && liveSocket) startLiveVision();
  } catch (e) {
    $('visionOut').textContent = 'Accès caméra refusé : ' + e.message;
  }
}

function stopCamera() {
  stopLiveVision();
  if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
  cameraStream = null;
  if ($('camera')) $('camera').srcObject = null;
  $('visionOut').textContent = 'Caméra inactive.';
}

async function captureVision() {
  const v = $('camera');
  if (!cameraStream || !v.videoWidth || !v.videoHeight) {
    $('visionOut').textContent = 'Active la caméra d’abord.';
    return;
  }
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 960 / v.videoWidth);
  canvas.width = Math.round(v.videoWidth * scale);
  canvas.height = Math.round(v.videoHeight * scale);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
  $('visionOut').textContent = 'Analyse de l’image...';

  try {
    const imageData = canvas.toDataURL('image/jpeg', 0.65);
    const d = await api('/api/vision/analyze', { ...jsonOptions('POST', { user_id: USER_ID, image_data_url: imageData, prompt: 'Décris ce que tu vois.' }) });
    $('visionOut').textContent = 'Ce que Chappie voit :\n' + d.description;
    
    const answer = await api('/api/chat', { ...jsonOptions('POST', { user_id: USER_ID, message: `Voici ce que tu vois par ta caméra : ${d.description}. Réagis naturellement.` }) });
    $('out').textContent = answer.reply;
    if (answer.psychology) renderEmotionsDashboard(answer.psychology);
    await speak(answer.reply);
  } catch (e) {
    $('visionOut').textContent = 'Erreur vision : ' + e.message;
  }
}

// --- Enregistrement Profils Vocaux ---
function wavBlob(floatSamples, sampleRate) {
  const rate = 16000, s = resample(floatSamples, sampleRate, rate), buf = new ArrayBuffer(44 + s.length * 2), v = new DataView(buf);
  const write = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  write(0, 'RIFF'); v.setUint32(4, 36 + s.length * 2, true); write(8, 'WAVE');
  write(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  write(36, 'data'); v.setUint32(40, s.length * 2, true);
  for (let i = 0; i < s.length; i++) {
    const x = Math.max(-1, Math.min(1, s[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 32768 : x * 32767, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

async function recordVoice(mode) {
  if (!navigator.mediaDevices?.getUserMedia) { $('voiceStatus').textContent = 'Micro non disponible.'; return; }
  const vName = $('voiceName');
  if (mode === 'enroll' && (!vName || !vName.value.trim())) { $('voiceStatus').textContent = 'Saisis un nom de profil.'; return; }
  
  let stream, ctx, src, proc, samples = [], sr;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    sr = ctx.sampleRate;
    src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = e => samples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(proc); proc.connect(ctx.destination);
    
    $('voiceStatus').textContent = 'Enregistrement en cours... Parle.';
    await new Promise(resolve => setTimeout(resolve, (mode === 'enroll' ? 8 : 5) * 1000));
    
    proc.disconnect(); src.disconnect(); stream.getTracks().forEach(t => t.stop()); await ctx.close();
    
    const n = samples.reduce((a, b) => a + b.length, 0), all = new Float32Array(n);
    let pos = 0;
    for (const a of samples) { all.set(a, pos); pos += a.length; }
    const blob = wavBlob(all, sr);
    
    const endpoint = mode === 'enroll' ? '/api/voice-profiles/' + encodeURIComponent(vName.value.trim()) : '/api/voice-profiles-identify';
    const r = await fetch(endpoint, { method: 'POST', headers: { ...headers(false), 'Content-Type': 'audio/wav' }, body: blob });
    const d = await r.json();
    if (!r.ok) throw Error(d.detail || 'Erreur profils vocaux');
    
    $('voiceStatus').textContent = mode === 'enroll' ? 'Profil enregistré : ' + d.profile_name : ('Résultat : ' + (d.profile_name || 'Inconnu') + ' (score ' + (d.score ?? '—') + ')');
  } catch (e) {
    $('voiceStatus').textContent = 'Erreur : ' + e.message;
  }
}

// --- Initialisation globale ---
window.addEventListener('DOMContentLoaded', () => {
  setStatus('Interface chargée.');
  fetchPsychology();
  const msgInput = $('msg');
  if (msgInput) {
    msgInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }
});

// Exposer globalement pour le HTML
window.sendMessage = sendMessage;
window.stopSpeech = stopSpeech;
window.toggleMic = toggleMic;
window.loadSummary = loadSummary;
window.loadMoodHistory = loadMoodHistory;
window.loadDreams = loadDreams;
window.loadThoughts = loadThoughts;
window.loadSkills = loadSkills;
window.resetLife = resetLife;
window.loadGoals = loadGoals;
window.consolidate = consolidate;
window.toggleLive = toggleLive;
window.startCamera = startCamera;
window.stopCamera = stopCamera;
window.captureVision = captureVision;
window.recordVoice = recordVoice;
