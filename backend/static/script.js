let recognition = null;
let speakingAudio = null;

const $ = id => document.getElementById(id);

function headers() {
  return {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + $('token').value.trim()
  };
}

function setStatus(s) {
  $('status').textContent = s;
}

// --- Rendu visuel du tableau de bord émotionnel ---
function renderEmotionsDashboard(psy, lastEvent = null) {
  const container = $('state');
  if (!container || !psy) return;

  // Si l'élément est une balise PRE, on le remplace par un conteneur stylé
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

// --- Polling dynamique pour rafraîchir le tableau de bord émotionnel et les événements ---
async function fetchPsychology() {
  try {
    const token = $('token') ? $('token').value.trim() : '';
    if (!token) return;
    const r = await fetch('/api/emotions/creator', { headers: headers() });
    if (r.ok) {
      const d = await r.json();
      
      // Essai de récupération du dernier événement d'humeur
      let lastEvent = null;
      try {
        const moodRes = await fetch('/api/mood/history?limit=1', { headers: headers() });
        if (moodRes.ok) {
          const moodData = await moodRes.json();
          if (moodData.events && moodData.events.length > 0) {
            lastEvent = moodData.events[0].event;
          }
        }
      } catch (e) {}

      if (d.psychology) renderEmotionsDashboard(d.psychology, lastEvent);
    }
  } catch (e) {
    // Ignorer silencieusement les petites coupures réseau
  }
}

// Actualisation automatique toutes les 4 secondes pour que les jauges restent vivantes
setInterval(fetchPsychology, 4000);

window.addEventListener('DOMContentLoaded', () => {
  setStatus('Interface chargée. Jeton requis pour les fonctions protégées.');
  console.info('Chappie interface prête');
});

async function sendMessage() {
  const message = $('msg').value.trim();
  if (!message) return;
  
  const btn = $('sendBtn');
  btn.disabled = true;
  setStatus('Chappie réfléchit...');
  $('out').textContent = 'Réflexion...';
  
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ user_id: 'creator', message })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Erreur API');
    
    $('out').textContent = d.reply;
    if (d.psychology) {
      renderEmotionsDashboard(d.psychology);
      fetchPsychology(); // Rafraîchit l'événement émotionnel récent
    }
    $('msg').value = '';
    setStatus('Réponse reçue.');
    await speak(d.reply);
  } catch (e) {
    $('out').textContent = 'Erreur : ' + e.message;
    setStatus('Vérifie le jeton, la connexion et la configuration Gemini.');
  } finally {
    btn.disabled = false;
  }
}

// --- Synthèse vocale avec Pitch dynamique selon le niveau de maturité (Web Audio API) ---
async function speak(text) {
  try {
    if (speakingAudio) {
      speakingAudio.pause();
      URL.revokeObjectURL(speakingAudio.src);
    }
    
    // Récupérer le niveau global de maturité de Chappie pour ajuster le pitch vocal
    let maturityLevel = 1.0;
    try {
      const skillRes = await fetch('/api/skills/creator', { headers: headers() });
      if (skillRes.ok) {
        const skillData = await skillRes.json();
        if (skillData.average_level) {
          maturityLevel = skillData.average_level;
        }
      }
    } catch (e) {}

    const r = await fetch('/api/speak', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ text, voice: 'fr-FR-HenriNeural' })
    });
    if (!r.ok) {
      setStatus('Réponse écrite prête ; synthèse vocale indisponible.');
      return;
    }
    
    const arrayBuffer = await r.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;

    // Calcul du pitch : Niveau 1 = très aigu (1.35), Niveau 10 = naturel adulte (1.00)
    const playbackRate = Math.max(1.0, Math.min(1.35, 1.35 - (0.35 * (maturityLevel - 1) / 9)));
    source.playbackRate.value = playbackRate;

    source.connect(audioCtx.destination);
    
    // Convertir l'audio modifié en Blob pour garder la compatibilité avec l'élément audio si besoin
    source.start(0);
    setStatus('Lecture vocale en cours (Maturité : ' + maturityLevel.toFixed(1) + '/10)...');

    source.onended = () => {
      setStatus('Prêt.');
      audioCtx.close();
    };
  } catch (e) {
    setStatus('Réponse écrite prête ; lecture vocale impossible dans ce navigateur.');
  }
}

function stopSpeech() {
  if (speakingAudio) {
    speakingAudio.pause();
    speakingAudio.currentTime = 0;
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  setStatus('Lecture arrêtée.');
}

function toggleMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    setStatus('La dictée vocale nécessite un navigateur compatible, par exemple Chrome.');
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
    setStatus('Dictée terminée. Vérifie le texte puis envoie-le.');
  };
  $('micBtn').textContent = '⏹️ Arrêter dictée';
  setStatus('Je t’écoute...');
  recognition.start();
}

async function loadSummary() {
  try {
    const r = await fetch('/api/memory/summary', { headers: headers() });
    const d = await r.json();
    $('summary').textContent = r.ok ? (d.summary || 'Aucun résumé enregistré pour le moment.') : d.detail;
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement.';
  }
}

// --- Chargement de l'historique des 10 dernières humeurs ---
async function loadMoodHistory() {
  try {
    const r = await fetch('/api/mood/history?limit=10', { headers: headers() });
    const d = await r.json();
    if (r.ok && d.events) {
      if (d.events.length === 0) {
        $('summary').textContent = 'Aucun événement d’humeur enregistré pour le moment.';
        return;
      }
      let text = "📜 Historique des 10 dernières humeurs :\n\n";
      d.events.forEach(e => {
        const date = new Date(e.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const valSign = e.valence > 0 ? '+' : '';
        text += `• [${date}] ${e.event} (Valence: ${valSign}${e.valence})\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Impossible de charger l’historique des humeurs.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement des humeurs : ' + e.message;
  }
}

// --- Chargement des derniers rêves simulés (Étape 4) ---
async function loadDreams() {
  try {
    const r = await fetch('/api/dreams/creator', { headers: headers() });
    const d = await r.json();
    if (r.ok && d.dreams) {
      if (d.dreams.length === 0) {
        $('summary').textContent = 'Aucun rêve simulé enregistré pour le moment.';
        return;
      }
      let text = "🌙 Derniers rêves simulés de Chappie :\n\n";
      d.dreams.forEach(dream => {
        const date = new Date(dream.created_at).toLocaleString('fr-FR');
        text += `• [${date}]\n  "${dream.content}"\n\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Impossible de charger les rêves.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement des rêves : ' + e.message;
  }
}

// --- Chargement des dernières pensées / ruminations (Métacognition) ---
async function loadThoughts() {
  try {
    const r = await fetch('/api/thoughts/creator', { headers: headers() });
    const d = await r.json();
    if (r.ok && d.thoughts) {
      if (d.thoughts.length === 0) {
        $('summary').textContent = 'Aucune pensée métacognitive enregistrée pour le moment.';
        return;
      }
      let text = "🧠 Dernières pensées et ruminations de Chappie :\n\n";
      d.thoughts.forEach(t => {
        const date = new Date(t.created_at).toLocaleString('fr-FR');
        text += `• [${date}]\n  "${t.content}"\n\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Impossible de charger les pensées.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement des pensées : ' + e.message;
  }
}

// --- Chargement de l'Arbre de Compétences (Axe 4) ---
async function loadSkills() {
  try {
    const r = await fetch('/api/skills/creator', { headers: headers() });
    const d = await r.json();
    if (r.ok && d.skills) {
      if (d.skills.length === 0) {
        $('summary').textContent = 'Aucune compétence enregistrée pour le moment.';
        return;
      }
      let text = `🎓 Arbre de Compétences de Chappie (Moyenne globale : ${(d.average_level || 1).toFixed(1)}/10) :\n\n`;
      d.skills.forEach(s => {
        const percent = Math.min(100, Math.round((s.xp % 100)));
        text += `🔹 ${s.evidence || s.skill_name} : Niveau ${Math.round(s.level)} (XP: ${Math.round(s.xp)} - ${percent}% niv suivant)\n`;
      });
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Impossible de charger les compétences.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement des compétences : ' + e.message;
  }
}

// --- Réinitialisation Page Blanche (Reset de vie) ---
async function resetLife() {
  if (!confirm("⚠️ Es-tu sûr de vouloir effacer toute la mémoire et réinitialiser Chappie à zéro (Page Blanche / Naissance) ?")) {
    return;
  }
  try {
    setStatus('Réinitialisation de Chappie en cours...');
    const r = await fetch('/api/reset-life', {
      method: 'POST',
      headers: headers()
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Erreur lors du reset');
    
    $('summary').textContent = "🐣 Chappie est né à nouveau (Stade 0). Tout est effacé, prêt pour l'apprentissage !";
    $('out').textContent = "Bip... Où suis-je ? Bonjour... c'est quoi cet endroit ?";
    setStatus('Chappie est un nouveau-né !');
    fetchPsychology();
  } catch (e) {
    setStatus('Erreur de réinitialisation : ' + e.message);
  }
}

// --- Chargement des objectifs actifs (Étape 4) ---
async function loadGoals() {
  try {
    const r = await fetch('/api/goals', { headers: headers() });
    const d = await r.json();
    if (r.ok && d.goals) {
      if (d.goals.length === 0) {
        $('summary').textContent = 'Aucun objectif actif pour le moment.';
        return;
      }
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
      $('summary').textContent = text;
    } else {
      $('summary').textContent = 'Impossible de charger les objectifs.';
    }
  } catch (e) {
    $('summary').textContent = 'Erreur de chargement des objectifs : ' + e.message;
  }
}

async function consolidate() {
  try {
    const r = await fetch('/api/memory/consolidate', { method: 'POST', headers: headers() });
    const d = await r.json();
    $('summary').textContent = r.ok ? (d.summary || 'Aucun échange à résumer.') : d.detail;
    setStatus(r.ok ? 'Mémoire consolidée.' : 'Consolidation impossible.');
  } catch (e) {
    setStatus('Erreur de consolidation.');
  }
}

// --- Gemini Live ---
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
    for (let j = start; j < end; j++) {
      sum += input[j];
      n++;
    }
    out[i] = n ? sum / n : input[start] || 0;
  }
  return out;
}

// Envoi en continu du flux vidéo de la caméra dans Gemini Live
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
      video: {
        mimeType: 'image/jpeg',
        data: base64Image
      }
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
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    liveCtx = new (window.AudioContext || window.webkitAudioContext)();
    await liveCtx.resume();
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    liveSocket = new WebSocket(proto + '//' + location.host + '/ws/live?token=' + encodeURIComponent($('token').value.trim()));
    window.liveSocket = liveSocket;
    
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

      if (cameraStream) {
        startLiveVision();
      }
    };
    
    liveSocket.onmessage = e => {
      let d;
      try { d = JSON.parse(e.data); } catch { return; }
      if (d.status) { $('liveStatus').textContent = d.status; return; }
      if (d.interrupt) {
        for (const a of liveAudioSources) { try { a.stop(); } catch {} }
        liveAudioSources.clear();
        liveNextTime = liveCtx ? liveCtx.currentTime : 0;
      }
      if (d.text) { $('out').textContent += ('\nChappie : ' + d.text); }
      if (d.audio) { playLiveAudio(d.audio, d.sample_rate || 24000); }
      if (d.error) { $('liveStatus').textContent = 'Erreur : ' + d.error; }

      // Rafraîchir les barres d'émotions pendant le live
      if (d.psychology) {
        renderEmotionsDashboard(d.psychology);
      } else {
        fetchPsychology();
      }
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
  const bytes = fromB64(encoded);
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), f = new Float32Array(Math.floor(bytes.length / 2));
  for (let i = 0; i < f.length; i++) f[i] = dv.getInt16(i * 2, true) / 32768;
  const buf = liveCtx.createBuffer(1, f.length, rate);
  buf.copyToChannel(f, 0);
  const src = liveCtx.createBufferSource();
  src.buffer = buf;
  src.connect(liveCtx.destination);
  liveAudioSources.add(src);
  src.onended = () => liveAudioSources.delete(src);
  const now = liveCtx.currentTime;
  liveNextTime = Math.max(liveNextTime, now + .04);
  src.start(liveNextTime);
  liveNextTime += buf.duration;
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
  liveSocket = null; window.liveSocket = null; liveStream = null; liveCtx = null; liveProcessor = null; liveSource = null; liveNextTime = 0;
  $('liveBtn').textContent = '▶ Démarrer la conversation live';
}

// --- Vision ---
let cameraStream = null;

async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    $('camera').srcObject = cameraStream;
    $('visionOut').textContent = 'Caméra active. Chappie peut vous observer en direct si Gemini Live est lancé.';
    
    if (liveActive && liveSocket) {
      startLiveVision();
    }
  } catch (e) {
    $('visionOut').textContent = 'Accès caméra refusé ou indisponible : ' + e.message;
  }
}

function stopCamera() {
  stopLiveVision();
  if (cameraStream) cameraStream.getTracks().forEach(t => t.stop());
  cameraStream = null;
  $('camera').srcObject = null;
  $('visionOut').textContent = 'Caméra inactive.';
}

async function captureVision() {
  const v = $('camera');

  if (!cameraStream || !v.videoWidth || !v.videoHeight) {
    $('visionOut').textContent = 'Active la caméra et attends que l’image apparaisse.';
    return;
  }

  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 960 / v.videoWidth);

  canvas.width = Math.round(v.videoWidth * scale);
  canvas.height = Math.round(v.videoHeight * scale);

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    $('visionOut').textContent = 'Impossible de préparer l’image.';
    return;
  }

  ctx.drawImage(v, 0, 0, canvas.width, canvas.height);

  $('visionOut').textContent = 'Chappie observe l’image...';

  try {
    const imageData = canvas.toDataURL('image/jpeg', 0.65);

    const visionResponse = await fetch('/api/vision/analyze', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        image_data_url: imageData,
        prompt: 'Décris ce que tu vois. Distingue les éléments certains des suppositions. Si une personne est visible, décris son apparence sans chercher à déterminer son identité.'
      })
    });

    const visionData = await visionResponse.json();

    if (!visionResponse.ok) {
      throw new Error(
        visionData.detail || 'L’analyse visuelle a échoué.'
      );
    }

    const description = visionData.description;

    $('visionOut').textContent =
      'Ce que Chappie voit :\n' + description +
      '\n\nChappie prépare sa réponse...';

    const chatResponse = await fetch('/api/chat', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        user_id: 'creator',
        message:
          'Tu viens d’analyser une image avec ta caméra. ' +
          'Voici la description obtenue :\n' +
          description +
          '\nRéagis naturellement à ce que tu observes et explique-moi ce que tu en comprends.'
      })
    });

    const chatData = await chatResponse.json();

    if (!chatResponse.ok) {
      throw new Error(
        chatData.detail ||
        'Image analysée, mais Chappie ne peut pas répondre.'
      );
    }

    $('visionOut').textContent =
      'Ce que Chappie voit :\n' + description;

    $('out').textContent = chatData.reply;
    if (chatData.psychology) {
      renderEmotionsDashboard(chatData.psychology);
      fetchPsychology();
    }

    setStatus('Image analysée et réponse de Chappie reçue.');

    await speak(chatData.reply);

  } catch (e) {
    $('visionOut').textContent =
      'Erreur caméra : ' + e.message;
    setStatus('Vérifie le jeton et la connexion au serveur.');
  }
}

// --- Profils Vocaux ---
function wavBlob(floatSamples, sampleRate) {
  const rate = 16000, s = resample(floatSamples, sampleRate, rate), buf = new ArrayBuffer(44 + s.length * 2), v = new DataView(buf);
  const write = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  write(0, 'RIFF');
  v.setUint32(4, 36 + s.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  write(36, 'data');
  v.setUint32(40, s.length * 2, true);
  for (let i = 0; i < s.length; i++) {
    const x = Math.max(-1, Math.min(1, s[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 32768 : x * 32767, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

async function recordVoice(mode) {
  if (!navigator.mediaDevices?.getUserMedia) {
    $('voiceStatus').textContent = 'Micro non disponible.';
    return;
  }
  if (mode === 'enroll' && !$('voiceName').value.trim()) {
    $('voiceStatus').textContent = 'Saisis un nom de profil.';
    return;
  }
  let stream, ctx, src, proc, samples = [], sr;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    sr = ctx.sampleRate;
    src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = e => samples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(proc);
    proc.connect(ctx.destination);
    
    $('voiceStatus').textContent = 'Enregistrement ' + (mode === 'enroll' ? 'du profil' : 'de comparaison') + '... parle naturellement.';
    await new Promise(resolve => setTimeout(resolve, (mode === 'enroll' ? 8 : 5) * 1000));
    
    proc.disconnect();
    src.disconnect();
    stream.getTracks().forEach(t => t.stop());
    await ctx.close();
    
    const n = samples.reduce((a, b) => a + b.length, 0), all = new Float32Array(n);
    let pos = 0;
    for (const a of samples) {
      all.set(a, pos);
      pos += a.length;
    }
    const blob = wavBlob(all, sr);
    const formHeaders = { 'Authorization': 'Bearer ' + $('token').value.trim(), 'Content-Type': 'audio/wav' };
    const endpoint = mode === 'enroll' ? '/api/voice-profiles/' + encodeURIComponent($('voiceName').value.trim()) : '/api/voice-profiles-identify';
    const r = await fetch(endpoint, { method: 'POST', headers: formHeaders, body: blob });
    const d = await r.json();
    if (!r.ok) throw Error(d.detail || 'Erreur profils vocaux');
    
    $('voiceStatus').textContent = mode === 'enroll' ? 'Profil enregistré : ' + d.profile_name : ('Résultat : ' + (d.profile_name || 'personne non reconnue') + ' (score ' + (d.score ?? '—') + ')');
  } catch (e) {
    $('voiceStatus').textContent = 'Profils vocaux : ' + e.message;
  }
}

// Écouteur de touche Entrée
window.addEventListener('DOMContentLoaded', () => {
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

// --- Exposer globalement les fonctions pour le HTML ---
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
