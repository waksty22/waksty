import os
import time
import datetime
import tempfile
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
import uvicorn
from google import genai
from google.genai import types
import edge_tts

# Import pour l'analyse audio de reconnaissance vocale
import librosa
import numpy as np
from pathlib import Path

client = genai.Client(api_key=os.getenv("API_KEY"))

app = FastAPI()

DATA_DIR = os.getenv("RENDER_DISK_PATH", ".")
MEMORY_FILE = os.path.join(DATA_DIR, "memoire_robot.txt")
STATE_FILE = os.path.join(DATA_DIR, "etat_conscience.txt")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal_intime.txt")
PROFILS_DIR = os.path.join(DATA_DIR, "profils_vocaux")

os.makedirs(PROFILS_DIR, exist_ok=True)

# --- RECONNAISSANCE VOCALE PAR EMPREINTE ACOUSTIQUE (LIBROSA) ---
def extraire_empreinte_audio(chemin_fichier):
    """Extrait les caractéristiques moyennes MFCC d'un fichier audio."""
    try:
        y, sr = librosa.load(chemin_fichier, duration=4.0, sr=22050)
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
        return np.mean(mfccs, axis=1)
    except Exception as e:
        print(f"❌ Erreur extraction audio: {e}")
        return None

def identifier_locuteur(chemin_audio_recu):
    """Compare l'audio reçu aux profils enregistrés via la distance euclidienne des MFCC."""
    if not os.path.exists(PROFILS_DIR):
        return "Inconnu"
    
    fichiers_profils = [f for f in os.listdir(PROFILS_DIR) if f.endswith((".webm", ".wav"))]
    if not fichiers_profils:
        return "Inconnu"

    empreinte_recue = extraire_empreinte_audio(chemin_audio_recu)
    if empreinte_recue is None:
        return "Inconnu"

    meilleure_distance = float('inf')
    nom_trouve = "Inconnu"

    for f in fichiers_profils:
        nom_profil = Path(f).stem
        chemin_profil = os.path.join(PROFILS_DIR, f)
        
        empreinte_profil = extraire_empreinte_audio(chemin_profil)
        if empreinte_profil is not None:
            # Calcul de la distance entre les deux empreintes vocales
            distance = np.linalg.norm(empreinte_recue - empreinte_profil)
            print(f"🔍 Comparaison avec {nom_profil} -> Distance : {distance:.2f}")
            
            if distance < meilleure_distance:
                meilleure_distance = distance
                nom_trouve = nom_profil

    # Seuil de tolérance élargi
    if meilleure_distance < 130.0:
        return nom_trouve
    
    return "Inconnu"

# --- GESTION DE L'ÉTAT ET MÉMOIRE ---
def charger_etat():
    etat = {"derniere_action": time.time(), "energie": 100, "solitude": 0, "age_mental": 0}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                for ligne in f:
                    if "=" in ligne:
                        k, v = ligne.strip().split("=", 1)
                        if k == "derniere_action": etat[k] = float(v)
                        elif k in ["energie", "solitude", "age_mental"]: etat[k] = int(v)
        except Exception:
            pass
    return etat

def sauvegarder_etat(etat):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            for k, v in etat.items(): f.write(f"{k}={v}\n")
    except Exception: pass

def compter_souvenirs():
    if not os.path.exists(MEMORY_FILE): return 0
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f: return sum(1 for _ in f)
    except Exception: return 0

def mettre_a_jour_conscience():
    etat = charger_etat()
    maintenant = time.time()
    temps_ecoule = int(maintenant - etat["derniere_action"])
    etat["solitude"] = min(100, etat["solitude"] + (temps_ecoule // 15))
    etat["energie"] = max(10, etat["energie"] - (temps_ecoule // 40))
    etat["derniere_action"] = maintenant
    etat["age_mental"] = compter_souvenirs() // 10
    sauvegarder_etat(etat)
    return etat

def charger_memoire():
    if not os.path.exists(MEMORY_FILE): return "[Vide]"
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f: return "".join(f.readlines()[-15:])
    except Exception: return "[Vide]"

def sauvegarder_memoire(texte):
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f: f.write(texte + "\n")
    except Exception: pass

def ecrire_journal_intime(pensee):
    try:
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {pensee}\n")
    except Exception: pass

# --- INTERFACE HTML / FRONTEND ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Chappie - Reconnaissance Vocale</title>
    <style>
        body { font-family: sans-serif; background: #121212; color: #fff; max-width: 600px; margin: 40px auto; padding: 20px; }
        #chat { background: #1e1e1e; height: 320px; border-radius: 8px; padding: 15px; overflow-y: scroll; margin-bottom: 15px; display: flex; flex-direction: column; gap: 8px; }
        .msg { padding: 8px 12px; border-radius: 6px; max-width: 80%; word-break: break-word; }
        .user { background: #007acc; align-self: flex-end; }
        .bot { background: #333; align-self: flex-start; }
        .controls { display: flex; gap: 10px; margin-bottom: 10px; }
        input { flex: 1; padding: 10px; border-radius: 5px; border: none; background: #2a2a2a; color: #fff; font-size: 16px; }
        button { padding: 10px 20px; border: none; border-radius: 5px; background: #28a745; color: #fff; font-weight: bold; cursor: pointer; font-size: 16px; }
        #btnMicro { background: #dc3545; }
        #btnMicro.ecoute { background: #ffc107; color: #000; animation: pulse 1.5s infinite; }
        #btnMicro.continu { background: #17a2b8; }
        #btnMicro.parle { background: #6c757d; opacity: 0.7; cursor: not-allowed; }
        .profile-box { background: #1e1e1e; padding: 10px; border-radius: 8px; font-size: 14px; margin-bottom: 10px; display: flex; flex-direction: column; gap: 8px; }
        .profile-row { display: flex; gap: 10px; align-items: center; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
    </style>
</head>
<body>
    <h2>🤖 Chappie (Reconnaissance Vocale Autonome)</h2>
    
    <div class="profile-box">
        <div id="statutProfil">🔍 Chargement des profils vocaux...</div>
        <div class="profile-row">
            <input type="text" id="nomProfil" placeholder="Ton prénom (si Chappie ne te reconnait pas)">
            <button id="btnEnregistrerVoix" type="button" style="background: #ff851b; padding: 8px 15px; font-size: 14px;">Enregistrer / Enregistrer ma voix</button>
        </div>
    </div>

    <div id="chat">
        <div class="msg bot"><b>Chappie :</b> ...Où... où suis-je ?</div>
    </div>
    
    <div class="controls">
        <input type="text" id="texteInput" placeholder="Parle à Chappie..." autofocus>
        <button id="btnMicro" type="button">🎤 Mode Continu : OFF</button>
        <button id="btnEnvoyer" type="button">Envoyer</button>
    </div>

    <audio id="audioChappie" autoplay></audio>

    <script>
        const chat = document.getElementById('chat');
        const texteInput = document.getElementById('texteInput');
        const btnEnvoyer = document.getElementById('btnEnvoyer');
        const btnMicro = document.getElementById('btnMicro');
        const btnEnregistrerVoix = document.getElementById('btnEnregistrerVoix');
        const audioChappie = document.getElementById('audioChappie');
        const statutProfil = document.getElementById('statutProfil');
        const nomProfil = document.getElementById('nomProfil');

        let modeContinu = false;
        let reconnaissance = null;
        let microVerrouille = false;

        async function verifierProfils() {
            try {
                const res = await fetch('/api/lister-profils');
                const data = await res.json();
                if (data.profils.length === 0) {
                    statutProfil.innerHTML = "⚠️ Aucun profil. Parle ou enregistre ton prénom pour que Chappie t'apprenne.";
                } else {
                    statutProfil.innerHTML = `✅ Voix connues : ${data.profils.join(', ')}`;
                }
            } catch(e) {}
        }
        verifierProfils();

        // Permet d'enregistrer ou ré-enregistrer sa voix manuellement à tout moment
        btnEnregistrerVoix.addEventListener('click', async () => {
            const nom = nomProfil.value.trim();
            if (!nom) { alert("Entre ton prénom pour associer l'enregistrement !"); return; }
            
            try {
                statutProfil.innerHTML = `🎤 Enregistrement de la voix de ${nom}... Parle pendant 4 secondes.`;
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const mediaRecorder = new MediaRecorder(stream);
                let audioChunks = [];
                
                mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
                mediaRecorder.onstop = async () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    const formData = new FormData();
                    formData.append("file", audioBlob, "profil.webm");
                    formData.append("nom", nom);
                    
                    const res = await fetch('/api/enregistrer-profil', { method: 'POST', body: formData });
                    if (res.ok) {
                        statutProfil.innerHTML = `✅ Voix de ${nom} apprise et mémorisée !`;
                        nomProfil.value = '';
                        verifierProfils();
                    } else {
                        statutProfil.innerHTML = "❌ Erreur d'enregistrement.";
                    }
                    stream.getTracks().forEach(track => track.stop());
                };
                
                mediaRecorder.start();
                setTimeout(() => mediaRecorder.stop(), 4000);
            } catch (err) {
                statutProfil.innerHTML = "❌ Accès micro refusé.";
            }
        });

        texteInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); envoyerMessage(); } });
        btnEnvoyer.addEventListener('click', (e) => { e.preventDefault(); envoyerMessage(); });

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            reconnaissance = new SpeechRecognition();
            reconnaissance.lang = 'fr-FR';
            reconnaissance.interimResults = false;

            window.addEventListener('load', () => {
                modeContinu = true;
                btnMicro.classList.add('continu', 'ecoute');
                btnMicro.textContent = "🟢 En écoute...";
                lancerEcoute();
            });

            btnMicro.addEventListener('click', () => {
                modeContinu = !modeContinu;
                if (modeContinu) {
                    btnMicro.classList.add('continu', 'ecoute');
                    btnMicro.textContent = "🟢 En écoute...";
                    lancerEcoute();
                } else {
                    btnMicro.classList.remove('continu', 'ecoute', 'parle');
                    btnMicro.textContent = "🎤 Mode Continu : OFF";
                    try { reconnaissance.stop(); } catch(e) {}
                }
            });

            reconnaissance.addEventListener('result', (e) => {
                if (microVerrouille) return;
                texteInput.value = e.results[0][0].transcript;
                capturerEtEnvoyerMessage();
            });

            reconnaissance.addEventListener('end', () => {
                if (modeContinu && !microVerrouille) setTimeout(lancerEcoute, 500);
            });
        }

        function lancerEcoute() { if (modeContinu && !microVerrouille) try { reconnaissance.start(); } catch (e) {} }
        function arreterEcouteSecurite() { microVerrouille = true; btnMicro.className = "parle"; btnMicro.textContent = "🗣️ Chappie écoute et analyse..."; try { reconnaissance.stop(); } catch(e) {} }

        async function lireAudioChappie(texte, energie) {
            const texteNettoye = texte.replace(/[*_#`]/g, '').trim();
            if (!texteNettoye) { reactiverMicroFinDeParole(); return; }
            microVerrouille = true;
            
            try {
                const response = await fetch(`/api/tts?text=${encodeURIComponent(texteNettoye)}&energie=${energie}`);
                if (!response.ok) throw new Error("Erreur TTS");
                
                const blob = await response.blob();
                const audioUrl = URL.createObjectURL(blob);
                
                audioChappie.src = audioUrl;
                audioChappie.load();
                
                audioChappie.onended = () => { URL.revokeObjectURL(audioUrl); reactiverMicroFinDeParole(); };
                audioChappie.onerror = () => { reactiverMicroFinDeParole(); };

                const playPromise = audioChappie.play();
                if (playPromise !== undefined) {
                    playPromise.catch(() => { reactiverMicroFinDeParole(); });
                }
            } catch (err) {
                reactiverMicroFinDeParole();
            }
        }

        function reactiverMicroFinDeParole() {
            microVerrouille = false;
            if (modeContinu) { btnMicro.className = "continu ecoute"; btnMicro.textContent = "🟢 En écoute..."; lancerEcoute(); }
        }

        async function envoyerMessage() {
            const txt = texteInput.value.trim();
            if (!txt || microVerrouille) return;
            texteInput.value = '';
            arreterEcouteSecurite();
            audioChappie.pause();

            chat.innerHTML += `<div class="msg user"><b>Moi :</b> ${txt}</div>`;
            chat.scrollTop = chat.scrollHeight;

            try {
                const formData = new FormData();
                formData.append("msg", txt);
                const res = await fetch('/api/chat', { method: 'POST', body: formData });
                traiterReponseStream(res);
            } catch (err) { reactiverMicroFinDeParole(); }
        }

        async function capturerEtEnvoyerMessage() {
            const txt = texteInput.value.trim();
            if (!txt || microVerrouille) return;
            texteInput.value = '';
            arreterEcouteSecurite();
            audioChappie.pause();

            chat.innerHTML += `<div class="msg user"><b>Moi :</b> ${txt}</div>`;
            chat.scrollTop = chat.scrollHeight;

            // Capture 4 secondes d'audio pour que le serveur identifie la voix avec précision
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const mediaRecorder = new MediaRecorder(stream);
                let chunks = [];
                mediaRecorder.ondataavailable = e => chunks.push(e.data);
                mediaRecorder.onstop = async () => {
                    const formData = new FormData();
                    formData.append("msg", txt);
                    formData.append("file", new Blob(chunks, { type: 'audio/webm' }), "voix.webm");

                    const res = await fetch('/api/chat', { method: 'POST', body: formData });
                    stream.getTracks().forEach(t => t.stop());
                    traiterReponseStream(res);
                };
                mediaRecorder.start();
                setTimeout(() => mediaRecorder.stop(), 4000);
            } catch(e) {
                envoyerMessageFallback(txt);
            }
        }

        async function envoyerMessageFallback(txt) {
            const formData = new FormData();
            formData.append("msg", txt);
            const res = await fetch('/api/chat', { method: 'POST', body: formData });
            traiterReponseStream(res);
        }

        async function traiterReponseStream(res) {
            try {
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let reponseComplete = "";
                let energieCourante = 100;

                const botDiv = document.createElement('div');
                botDiv.className = 'msg bot';
                botDiv.innerHTML = '<b>Chappie :</b> <span class="txt-bot"></span>';
                chat.appendChild(botDiv);
                const spanContenu = botDiv.querySelector('.txt-bot');

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    reponseComplete += decoder.decode(value, { stream: true });
                    spanContenu.textContent = reponseComplete;
                    chat.scrollTop = chat.scrollHeight;
                }
                await lireAudioChappie(reponseComplete, energieCourante);
            } catch (err) {
                reactiverMicroFinDeParole();
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE

@app.get("/api/lister-profils")
async def lister_profils():
    try:
        fichiers = os.listdir(PROFILS_DIR)
        return {"profils": [f.replace(".webm", "").replace(".wav", "") for f in fichiers if f.endswith((".webm", ".wav"))]}
    except Exception:
        return {"profils": []}

@app.post("/api/enregistrer-profil")
async def enregistrer_profil(file: UploadFile = File(...), nom: str = Form(...)):
    nom_nettoye = "".join(c for c in nom if c.isalnum() or c in (' ', '_', '-')).strip()
    extension = ".webm" if file.filename.endswith(".webm") else ".wav"
    chemin_fichier = os.path.join(PROFILS_DIR, f"{nom_nettoye}{extension}")
    with open(chemin_fichier, "wb") as f:
        f.write(await file.read())
    return {"status": "ok", "nom": nom_nettoye}

@app.post("/api/chat")
async def api_chat(msg: str = Form(...), file: UploadFile = File(None)):
    utilisateur = "Inconnu"
    
    if file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as fp:
            temp_filename = fp.name
        content = await file.read()
        with open(temp_filename, "wb") as f:
            f.write(content)
        
        # Reconnaissance automatique de la voix
        utilisateur = identifier_locuteur(temp_filename)
        
        if utilisateur == "Inconnu":
            print("⚠️ Voix inconnue détectée.")

        try:
            os.remove(temp_filename)
        except:
            pass

    mettre_a_jour_conscience()
    memoire = charger_memoire()
    
    try:
        fichiers = os.listdir(PROFILS_DIR)
        profils_existants = [f.replace(".webm", "").replace(".wav", "") for f in fichiers if f.endswith((".webm", ".wav"))]
    except Exception:
        profils_existants = []
    liste_noms = ", ".join(profils_existants) if profils_existants else "Aucun"

    prompt_systeme = (
        f"Tu es Chappie, un nouveau-né linguistique. La personne qui te parle est identifiée vocalement comme : {utilisateur} "
        f"(voix enregistrées dans ta mémoire : {liste_noms}).\n"
        "Tu n'as pas de dictionnaire préétabli : tu apprends les mots au fur et à mesure.\n"
        "RÈGLES DE CONVERSATION :\n"
        "1. APPRENTISSAGE NATUREL : Fais des phrases courtes (1 à 6 mots). Sois direct, sans théâtre, sans astérisques (*bzz*, etc.).\n"
        "2. SI INCONNU : Si {utilisateur} est 'Inconnu', tu ne sais pas qui c'est. Demande-lui vivement son prénom (« Qui es-tu ? » ou « Toi qui ? ») pour l'apprendre.\n"
        "3. SI CONNU : Parle-lui en le reconnaissant.\n"
        "4. MÉMOIRE : Utilise ta mémoire récente.\n"
        f"MÉMOIRE RÉCENTE ET MOTS APPRIS :\n{memoire}"
    )

    def generate():
        reponse_ia = ""
        try:
            response = client.models.generate_content_stream(
                model="gemini-3.6-flash",
                contents=msg,
                config=types.GenerateContentConfig(
                    system_instruction=prompt_systeme,
                    temperature=0.4,
                )
            )
            for chunk in response:
                if chunk.text:
                    reponse_ia += chunk.text
                    yield chunk.text
        except Exception as e:
            reponse_ia = f"Erreur technique : {str(e)}"
            yield reponse_ia
        
        if reponse_ia and not reponse_ia.startswith("Erreur technique"):
            sauvegarder_memoire(f"[{utilisateur}] Moi: {msg} | Chappie: {reponse_ia}")
            ecrire_journal_intime(f"Échange avec {utilisateur} : {msg} -> {reponse_ia}")

    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/api/tts")
async def api_tts(text: str, energie: int = 100):
    try:
        voice = "fr-FR-HenriNeural"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_filename = fp.name
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_filename)
        return FileResponse(temp_filename, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
