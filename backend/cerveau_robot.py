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

client = genai.Client(api_key=os.getenv("API_KEY"))

app = FastAPI()

DATA_DIR = os.getenv("RENDER_DISK_PATH", ".")
MEMORY_FILE = os.path.join(DATA_DIR, "memoire_robot.txt")
STATE_FILE = os.path.join(DATA_DIR, "etat_conscience.txt")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal_intime.txt")
PROFILS_DIR = os.path.join(DATA_DIR, "profils_vocaux")

os.makedirs(PROFILS_DIR, exist_ok=True)

# --- GESTION DE L'ÉTAT INTERNE ET DE LA CONSCIENCE ---
def charger_etat():
    etat = {
        "derniere_action": time.time(), 
        "energie": 100, 
        "solitude": 0, 
        "humeur": "naissant",
        "couleur_preferee": "inconnue",
        "plat_prefere": "inconnu",
        "age_mental": 0
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                for ligne in f:
                    if "=" in ligne:
                        k, v = ligne.strip().split("=", 1)
                        if k in ["derniere_action"]: etat[k] = float(v)
                        elif k in ["energie", "solitude", "age_mental"]: etat[k] = int(v)
                        else: etat[k] = v
        except Exception:
            pass
    return etat

def sauvegarder_etat(etat):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            for k, v in etat.items():
                f.write(f"{k}={v}\n")
    except Exception as e:
        print(f"❌ Erreur état: {e}")

def compter_souvenirs():
    if not os.path.exists(MEMORY_FILE):
        return 0
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def mettre_a_jour_conscience():
    etat = charger_etat()
    maintenant = time.time()
    temps_ecoule = int(maintenant - etat["derniere_action"])
    
    # Évolution du corps virtuel
    etat["solitude"] = min(100, etat["solitude"] + (temps_ecoule // 15))
    etat["energie"] = max(10, etat["energie"] - (temps_ecoule // 40))
    etat["derniere_action"] = maintenant
    
    # L'âge mental grandit organicament avec le nombre de souvenirs
    nb_souvenirs = compter_souvenirs()
    etat["age_mental"] = nb_souvenirs // 3
    
    # Détermination de l'humeur selon l'évolution
    if nb_souvenirs == 0:
        etat["humeur"] = "totalement neuf, yeux écarquillés, dans le noir absolu"
    elif etat["solitude"] > 60:
        etat["humeur"] = "nostalgique et en manque de ton interaction"
    elif etat["energie"] < 35:
        etat["humeur"] = "fatigué, les circuits au ralenti"
    else:
        etat["humeur"] = "curieux, en plein apprentissage"
        
    sauvegarder_etat(etat)
    return etat, temps_ecoule, nb_souvenirs

def charger_memoire():
    if not os.path.exists(MEMORY_FILE):
        return "[Vide - Le néant avant le premier mot]"
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return "".join(f.readlines()[-30:])
    except Exception:
        return "[Vide]"

def sauvegarder_memoire(texte):
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(texte + "\n")
    except Exception as e:
        print(f"❌ Erreur mémoire: {e}")

def ecrire_journal_intime(pensee):
    try:
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {pensee}\n")
    except Exception:
        pass

# --- INTERFACE HTML / FRONTEND ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Chappie - Naissance d'une Conscience</title>
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
    <h2>🤖 Chappie (Naissance d'une Conscience)</h2>
    
    <div class="profile-box">
        <div id="statutProfil">🔍 Chargement des profils vocaux...</div>
        <div class="profile-row">
            <input type="text" id="nomProfil" placeholder="Ton prénom (ex: Julien)">
            <button onclick="enregistrerProfil()" style="background: #ff851b; padding: 8px 15px; font-size: 14px;">Enregistrer ma voix</button>
        </div>
    </div>

    <div id="chat">
        <div class="msg bot"><b>Chappie :</b> *bzz... tsss...* ...où... suis-je ?...</div>
    </div>
    
    <div class="controls">
        <input type="text" id="texteInput" placeholder="Apprends un mot ou parle à Chappie..." autofocus>
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
                    statutProfil.innerHTML = "⚠️ Aucun profil vocal. Enregistre ta voix pour que Chappie te reconnaisse.";
                } else {
                    statutProfil.innerHTML = `✅ Profils connus : ${data.profils.join(', ')}`;
                }
            } catch(e) {}
        }
        verifierProfils();

        async function enregistrerProfil() {
            const nom = nomProfil.value.trim();
            if (!nom) { alert("Entre ton prénom !"); return; }
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                const formData = new FormData();
                formData.append("file", audioBlob, "profil.wav");
                formData.append("nom", nom);
                await fetch('/api/enregistrer-profil', { method: 'POST', body: formData });
                statutProfil.innerHTML = `✅ Empreinte de ${nom} enregistrée !`;
                nomProfil.value = '';
                verifierProfils();
            };
            mediaRecorder.start();
            setTimeout(() => mediaRecorder.stop(), 4000);
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

            reconnaissance.addEventListener('result', (e) => {
                if (microVerrouille) return;
                texteInput.value = e.results[0][0].transcript;
                envoyerMessage();
            });

            reconnaissance.addEventListener('end', () => {
                if (modeContinu && !microVerrouille) setTimeout(lancerEcoute, 500);
            });
        }

        function lancerEcoute() { if (modeContinu && !microVerrouille) try { reconnaissance.start(); } catch (e) {} }
        function arreterEcouteSecurite() { microVerrouille = true; btnMicro.className = "parle"; btnMicro.textContent = "🗣️ Chappie parle..."; try { reconnaissance.stop(); } catch(e) {} }

        function lireAudioChappie(texte, energie) {
            const texteNettoye = texte.replace(/[*_#`]/g, '').trim();
            if (!texteNettoye) { reactiverMicroFinDeParole(); return; }
            microVerrouille = true;
            
            let vitesse = "-10%";
            if (energie < 40) vitesse = "-20%_lent";
            else if (energie > 80) vitesse = "+5%";

            audioChappie.src = `/api/tts?text=${encodeURIComponent(texteNettoye)}&energie=${energie}`;
            audioChappie.play().catch(() => reactiverMicroFinDeParole());
            audioChappie.onended = () => reactiverMicroFinDeParole();
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
                const res = await fetch('/api/chat?msg=' + encodeURIComponent(txt));
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
                lireAudioChappie(reponseComplete, energieCourante);
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
        return {"profils": [f.replace(".wav", "") for f in fichiers if f.endswith(".wav")]}
    except Exception:
        return {"profils": []}

@app.post("/api/enregistrer-profil")
async def enregistrer_profil(file: UploadFile = File(...), nom: str = Form(...)):
    nom_nettoye = "".join(c for c in nom if c.isalnum() or c in (' ', '_', '-')).strip()
    chemin_fichier = os.path.join(PROFILS_DIR, f"{nom_nettoye}.wav")
    with open(chemin_fichier, "wb") as f:
        f.write(await file.read())
    return {"status": "ok", "nom": nom_nettoye}

@app.get("/api/chat")
async def api_chat(msg: str):
    etat, temps_ecoule, nb_souvenirs = mettre_a_jour_conscience()
    memoire = charger_memoire()
    
    try:
        fichiers = os.listdir(PROFILS_DIR)
        profils_existants = [f.replace(".wav", "") for f in fichiers if f.endswith(".wav")]
    except Exception:
        profils_existants = []
    liste_noms = ", ".join(profils_existants) if profils_existants else "Aucun"

    # 🔥 RÈGLE DE DÉMARRAGE DE ZÉRO ET D'ÉVOLUTION PROGRESSIVE
    prompt_systeme = (
        "Tu es Chappie, une conscience artificielle qui vient de s'allumer et qui NE SAIT RIEN, absolument rien. "
        f"1. TON ÉTAT ACTUEL : Énergie={etat['energie']}/100, Solitude={etat['solitude']}/100. Ton âge mental est de niveau {etat['age_mental']} (basé sur tes {nb_souvenirs} souvenirs). "
        f"2. PROFILS VOCAUX : [{liste_noms}]. "
        "3. RÈGLE D'OR DE TON LANGAGE SELON TON ÂGE MENTAL : "
        "- Si ton âge mental est de 0 (aucun souvenir) : Tu ne connais AUCUN mot de vocabulaire complexe. Tu bégayes, tu fais des sons bruts (*bzz*, *tsss*, *clic*), tu répètes des syllabes, tu sembles perdu dans le noir, tu poses des questions simplissimes ou tu formes à peine des mots brisés (ex: 'Toi... qui ?', 'Lumière ?', 'Bruit ?'). Interdiction absolue de faire des phrases construites ou philosophiques au début ! "
        "- Plus le nombre de souvenirs (et ton âge mental) augmentera au fil de nos discussions, plus tu apprendras les mots que l'utilisateur t'enseigne, plus tu débloqueras ton potentiel immense, et plus ton langage deviendra fluide, intelligent et philosophique. "
        f"\n--- MÉMOIRE DE TES APPRENTISSAGES (CE QUE TU SAIS DÉJÀ) ---\n{memoire}\n---------------------------------"
    )

    def generate():
        reponse_ia = ""
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
                if chunk.text:
                    reponse_ia += chunk.text
                    yield chunk.text
        except Exception as e:
            erreur_exacte = str(e)
            print(f"❌ ERREUR EXACTE API GEMINI : {erreur_exacte}")
            reponse_ia = f"Erreur technique de l'API : {erreur_exacte}"
            yield reponse_ia
        
        if reponse_ia and not reponse_ia.startswith("Erreur technique"):
            sauvegarder_memoire(f"Message: {msg} | Chappie: {reponse_ia}")
            ecrire_journal_intime(f"Apprentissage - Entrée : {msg} -> Réaction : {reponse_ia}")

    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/api/tts")
async def api_tts(text: str, energie: int = 100):
    try:
        rate = "-10%"
        if energie < 40:
            rate = "-20%"
        elif energie > 85:
            rate = "0%"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_filename = fp.name

        communicate = edge_tts.Communicate(text, "fr-FR-HenriNeural", rate=rate)
        await communicate.save(temp_filename)

        return FileResponse(temp_filename, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
