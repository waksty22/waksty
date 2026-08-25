import os
import time
import tempfile
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
import uvicorn
from google import genai
from google.genai import types
import edge_tts

# Initialisation de l'API Gemini
client = genai.Client(api_key=os.getenv("API_KEY"))

app = FastAPI()

DATA_DIR = os.getenv("RENDER_DISK_PATH", ".")
MEMORY_FILE = os.path.join(DATA_DIR, "memoire_robot.txt")
PROFILS_DIR = os.path.join(DATA_DIR, "profils_vocaux")

os.makedirs(PROFILS_DIR, exist_ok=True)

def charger_memoire():
    if not os.path.exists(MEMORY_FILE):
        return "[Vide - Aucun mot connu]"
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            lignes = f.readlines()
            return "".join(lignes[-15:])
    except Exception:
        return "[Vide]"

def sauvegarder_memoire(nouveau_souvenir):
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(nouveau_souvenir + "\n")
    except Exception as e:
        print(f"❌ Erreur sauvegarde mémoire: {e}")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Chappie Cloud - Reconnaissance Vocale Autonome</title>
    <style>
        body { font-family: sans-serif; background: #121212; color: #fff; max-width: 600px; margin: 40px auto; padding: 20px; }
        #chat { background: #1e1e1e; height: 300px; border-radius: 8px; padding: 15px; overflow-y: scroll; margin-bottom: 15px; display: flex; flex-direction: column; gap: 8px; }
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
    <h2>🤖 Chappie (Reconnaissance Vocale Intelligente)</h2>
    
    <div class="profile-box">
        <div id="statutProfil">🔍 Chargement...</div>
        <div class="profile-row">
            <input type="text" id="nomProfil" placeholder="Ton prénom pour enregistrer ta voix (ex: Julien, Fred...)">
            <button onclick="enregistrerProfil()" style="background: #ff851b; padding: 8px 15px; font-size: 14px;">Enregistrer ma voix</button>
        </div>
    </div>

    <div id="chat">
        <div class="msg bot"><b>Chappie :</b> ... m... ? </div>
    </div>
    
    <div class="controls">
        <input type="text" id="texteInput" placeholder="Apprends un mot à Chappie..." autofocus>
        <button id="btnMicro" type="button">🎤 Mode Continu : OFF</button>
        <button id="btnEnvoyer" type="button">Envoyer</button>
    </div>

    <audio id="audioChappie" style="display:none;"></audio>

    <script>
        const chat = document.getElementById('chat');
        const texteInput = document.getElementById('texteInput');
        const btnEnvoyer = document.getElementById('btnEnvoyer');
        const btnMicro = document.getElementById('btnMicro');
        const audioChappie = document.getElementById('audioChappie');
        const statutProfil = document.getElementById('statutProfil');
        const nomProfil = document.getElementById('nomProfil');

        let modeContinu = false;
        let reconnaissance = null;
        let microVerrouille = false;
        let mediaRecorder = null;
        let audioChunks = [];

        async function verifierProfils() {
            try {
                const res = await fetch('/api/lister-profils');
                const data = await res.json();
                if (data.profils.length === 0) {
                    statutProfil.innerHTML = "⚠️ Aucun profil enregistré. Enregistre ta voix pour que Chappie te reconnaisse.";
                } else {
                    statutProfil.innerHTML = `✅ Profils connus de Chappie : ${data.profils.join(', ')}`;
                }
            } catch(e) {
                statutProfil.innerHTML = "❌ Erreur de chargement des profils.";
            }
        }
        verifierProfils();

        async function enregistrerProfil() {
            const nom = nomProfil.value.trim();
            if (!nom) { alert("Entre ton prénom !"); return; }

            statutProfil.innerHTML = `🎙️ Enregistrement de la voix de ${nom} (4 secondes)... Parle !`;
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
                mediaRecorder.onstop = async () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    const formData = new FormData();
                    formData.append("file", audioBlob, "profil.wav");
                    formData.append("nom", nom);

                    statutProfil.innerHTML = "⏳ Enregistrement de l'empreinte...";
                    const res = await fetch('/api/enregistrer-profil', { method: 'POST', body: formData });
                    if (res.ok) {
                        statutProfil.innerHTML = `✅ Empreinte de ${nom} enregistrée ! Chappie te reconnaîtra désormais.`;
                        nomProfil.value = '';
                        verifierProfils();
                    } else {
                        statutProfil.innerHTML = "❌ Erreur lors de l'enregistrement.";
                    }
                };

                mediaRecorder.start();
                setTimeout(() => mediaRecorder.stop(), 4000);
            } catch (err) {
                alert("Micro inaccessible : " + err.message);
            }
        }

        texteInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); envoyerMessage(); } });
        btnEnvoyer.addEventListener('click', (e) => { e.preventDefault(); envoyerMessage(); });

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            reconnaissance = new SpeechRecognition();
            reconnaissance.lang = 'fr-FR';
            reconnaissance.interimResults = false;

            btnMicro.addEventListener('click', () => {
                modeContinu = !modeContinu;
                if (modeContinu) {
                    btnMicro.classList.add('continu');
                    btnMicro.textContent = "🟢 En écoute continue...";
                    lancerEcoute();
                } else {
                    btnMicro.classList.remove('continu', 'ecoute', 'parle');
                    btnMicro.textContent = "🎤 Mode Continu : OFF";
                    try { reconnaissance.stop(); } catch(e) {}
                }
            });

            reconnaissance.addEventListener('start', () => {
                if (modeContinu && !microVerrouille) {
                    btnMicro.classList.add('ecoute');
                    btnMicro.textContent = "🔴 J'écoute...";
                }
            });

            reconnaissance.addEventListener('result', (e) => {
                if (microVerrouille) return;
                const texteReconnu = e.results[0][0].transcript;
                texteInput.value = texteReconnu;
                envoyerMessage();
            });

            reconnaissance.addEventListener('end', () => {
                btnMicro.classList.remove('ecoute');
                if (modeContinu && !microVerrouille) {
                    setTimeout(lancerEcoute, 500);
                } else if (modeContinu && microVerrouille) {
                    btnMicro.className = "parle";
                    btnMicro.textContent = "🗣️ Chappie parle (Micro coupé)...";
                } else {
                    btnMicro.textContent = "🎤 Mode Continu : OFF";
                }
            });
        } else {
            btnMicro.style.display = 'none';
        }

        function lancerEcoute() {
            if (!modeContinu || microVerrouille) return;
            try { reconnaissance.start(); } catch (e) {}
        }

        function arreterEcouteSecurite() {
            microVerrouille = true;
            btnMicro.className = "parle";
            btnMicro.textContent = "🗣️ Chappie parle (Micro coupé)...";
            try { reconnaissance.stop(); } catch(e) {}
        }

        function lireAudioChappie(texte) {
            const texteNettoye = texte.replace(/[*_#`]/g, '').trim();
            if (!texteNettoye) { reactiverMicroFinDeParole(); return; }

            microVerrouille = true;
            audioChappie.src = '/api/tts?text=' + encodeURIComponent(texteNettoye);
            audioChappie.play().catch(() => reactiverMicroFinDeParole());
            audioChappie.onended = () => reactiverMicroFinDeParole();
        }

        function reactiverMicroFinDeParole() {
            microVerrouille = false;
            if (modeContinu) {
                btnMicro.className = "continu ecoute";
                btnMicro.textContent = "🟢 En écoute continue...";
                lancerEcoute();
            }
        }

        async function envoyerMessage() {
            const txt = texteInput.value.trim();
            if (!txt || microVerrouille) return;

            texteInput.value = '';
            arreterEcouteSecurite();
            audioChappie.pause();

            try {
                const res = await fetch('/api/chat?msg=' + encodeURIComponent(txt));
                if (!res.ok) throw new Error("Erreur HTTP: " + res.status);

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let reponseComplete = "";
                let locuteurDetecte = "Inconnu";
                let premierChunk = true;

                const botDiv = document.createElement('div');
                botDiv.className = 'msg bot';
                botDiv.innerHTML = '<b>Chappie :</b> <span class="txt-bot"></span>';
                chat.appendChild(botDiv);
                const spanContenu = botDiv.querySelector('.txt-bot');

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    let morceau = decoder.decode(value, { stream: true });
                    
                    if (premierChunk) {
                        // Le premier mot renvoyé par l'IA indique le locuteur détecté ou le début
                        premierChunk = false;
                    }
                    reponseComplete += morceau;
                    spanContenu.textContent = reponseComplete;
                    chat.scrollTop = chat.scrollHeight;
                }

                lireAudioChappie(reponseComplete);
            } catch (err) {
                console.error(err);
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
        profils = [f.replace(".wav", "") for f in fichiers if f.endswith(".wav")]
        return {"profils": profils}
    except Exception:
        return {"profils": []}

@app.post("/api/enregistrer-profil")
async def enregistrer_profil(file: UploadFile = File(...), nom: str = Form(...)):
    try:
        nom_nettoye = "".join(c for c in nom if c.isalnum() or c in (' ', '_', '-')).strip()
        if not nom_nettoye:
            raise HTTPException(status_code=400, detail="Nom invalide")
        
        chemin_fichier = os.path.join(PROFILS_DIR, f"{nom_nettoye}.wav")
        contents = await file.read()
        with open(chemin_fichier, "wb") as f:
            f.write(contents)
        return {"status": "ok", "nom": nom_nettoye}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat")
async def api_chat(msg: str):
    memoire = charger_memoire()
    
    # On récupère la liste des personnes enregistrées
    try:
        fichiers = os.listdir(PROFILS_DIR)
        profils_existants = [f.replace(".wav", "") for f in fichiers if f.endswith(".wav")]
    except Exception:
        profils_existants = []

    liste_noms = ", ".join(profils_existants) if profils_existants else "Aucun pour l'instant"

    prompt_systeme = (
        "Tu es Chappie, un nouveau-né cybernétique qui vient tout juste de s'éveiller. "
        "Tu découvres le monde et les mots pour la toute première fois. Ton vocabulaire est limité, hésitant, enfantin. "
        f"Voici les personnes dont tu connais les voix / les prénoms enregistrés : [{liste_noms}]. "
        "En fonction de ce que la personne dit ou de sa façon de parler, essaie de deviner ou de déduire qui te parle parmi cette liste. "
        "Si tu ne sais pas du tout, appelle la personne 'l'ami' ou 'inconnu'. "
        "RÈGLES : "
        "1. Reste simple, utilise des mots d'enfant, des hésitations (*bop*, *clic*). "
        "2. Appuie-toi sur tes souvenirs ci-dessous. "
        f"\n--- TES SOUVENIRS ---\n{memoire}\n---------------------"
    )

    def generate():
        reponse_ia = ""
        tentatives = 3
        succes = False

        for essai in range(tentatives):
            try:
                response = client.models.generate_content_stream(
                    model="gemini-3.6-flash",
                    contents=msg,
                    config=types.GenerateContentConfig(
                        system_instruction=prompt_systeme,
                        temperature=0.8,
                    )
                )

                for chunk in response:
                    morceau = chunk.text
                    if morceau:
                        reponse_ia += morceau
                        yield morceau
                succes = True
                break
            except Exception as e:
                print(f"❌ ERREUR API GEMINI : {str(e)}")
                if essai < tentatives - 1:
                    time.sleep(2)
                else:
                    reponse_ia = "Euh... tête... mal..."
                    yield reponse_ia
        
        if succes and reponse_ia:
            sauvegarder_memoire(f"Message: {msg} | Chappie: {reponse_ia}")

    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/api/tts")
async def api_tts(text: str):
    try:
        VOIX_EDGE = "fr-FR-HenriNeural"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_filename = fp.name

        communicate = edge_tts.Communicate(text, VOIX_EDGE)
        await communicate.save(temp_filename)

        return FileResponse(temp_filename, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
