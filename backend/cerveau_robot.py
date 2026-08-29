import os
import time
import datetime
import tempfile
import json
import re
import asyncio
from pathlib import Path

import numpy as np
import librosa

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse

import uvicorn
from google import genai
from google.genai import types
import edge_tts


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("API_KEY")

if not API_KEY:
    print("⚠️ API_KEY absente.")

client = genai.Client(api_key=API_KEY)

app = FastAPI(title="Chappie V2")


# ============================================================
# DOSSIERS / FICHIERS
# ============================================================

DATA_DIR = os.getenv("RENDER_DISK_PATH", ".")

MEMORY_FILE = os.path.join(DATA_DIR, "memoire_robot.txt")
STATE_FILE = os.path.join(DATA_DIR, "etat_conscience.txt")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal_intime.txt")
PEOPLE_FILE = os.path.join(DATA_DIR, "personnes.json")

PROFILS_DIR = os.path.join(DATA_DIR, "profils_vocaux")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILS_DIR, exist_ok=True)


# ============================================================
# OUTILS
# ============================================================

def nettoyer_nom(nom):
    nom = nom.strip()

    nom = "".join(
        c for c in nom
        if c.isalnum() or c in (" ", "_", "-")
    )

    nom = re.sub(r"\s+", "_", nom)

    return nom[:50]


def charger_json(chemin, valeur_defaut):
    if not os.path.exists(chemin):
        return valeur_defaut

    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return valeur_defaut


def sauvegarder_json(chemin, donnees):
    try:
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(
                donnees,
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print("❌ Erreur sauvegarde JSON :", e)


# ============================================================
# PERSONNES
# ============================================================

def charger_personnes():
    return charger_json(PEOPLE_FILE, {})


def sauvegarder_personnes(personnes):
    sauvegarder_json(PEOPLE_FILE, personnes)


def enregistrer_personne(nom):
    nom = nettoyer_nom(nom)

    if not nom:
        return

    personnes = charger_personnes()

    if nom not in personnes:
        personnes[nom] = {
            "nom": nom,
            "premiere_rencontre": datetime.datetime.now().isoformat(),
            "derniere_interaction": datetime.datetime.now().isoformat(),
            "nombre_interactions": 0
        }

    personnes[nom]["derniere_interaction"] = datetime.datetime.now().isoformat()
    personnes[nom]["nombre_interactions"] += 1

    sauvegarder_personnes(personnes)


# ============================================================
# RECONNAISSANCE VOCALE
# ============================================================

def extraire_empreinte_audio(chemin_fichier):
    """
    Extrait une empreinte acoustique plus riche qu'une simple
    moyenne MFCC.

    Cette méthode reste expérimentale :
    elle sert à identifier approximativement un locuteur,
    pas à authentifier une personne.
    """

    try:
        y, sr = librosa.load(
            chemin_fichier,
            duration=4.0,
            sr=22050,
            mono=True
        )

        if y is None or len(y) < 1000:
            return None

        # Normalisation du volume
        y = librosa.util.normalize(y)

        # MFCC
        mfcc = librosa.feature.mfcc(
            y=y,
            sr=sr,
            n_mfcc=20
        )

        # Delta
        delta = librosa.feature.delta(mfcc)

        # Delta-delta
        delta2 = librosa.feature.delta(
            mfcc,
            order=2
        )

        # Moyenne + écart-type
        features = np.concatenate([
            np.mean(mfcc, axis=1),
            np.std(mfcc, axis=1),
            np.mean(delta, axis=1),
            np.std(delta, axis=1),
            np.mean(delta2, axis=1),
            np.std(delta2, axis=1)
        ])

        # Normalisation finale
        norm = np.linalg.norm(features)

        if norm > 0:
            features = features / norm

        return features

    except Exception as e:
        print("❌ Erreur extraction voix :", e)
        return None


def distance_cosinus(a, b):
    try:
        denom = np.linalg.norm(a) * np.linalg.norm(b)

        if denom == 0:
            return 1.0

        similarity = np.dot(a, b) / denom

        return 1.0 - similarity

    except Exception:
        return 1.0


def trouver_profils():
    profils = []

    if not os.path.exists(PROFILS_DIR):
        return profils

    for fichier in os.listdir(PROFILS_DIR):
        if fichier.endswith((".webm", ".wav", ".mp3")):
            profils.append(
                Path(fichier).stem
            )

    return sorted(list(set(profils)))


def identifier_locuteur(chemin_audio_recu):
    """
    Compare la voix reçue avec les profils enregistrés.

    Retourne :
        nom
        score
    """

    empreinte_recue = extraire_empreinte_audio(
        chemin_audio_recu
    )

    if empreinte_recue is None:
        return "Inconnu", 1.0

    fichiers = [
        f for f in os.listdir(PROFILS_DIR)
        if f.endswith((".webm", ".wav", ".mp3"))
    ]

    if not fichiers:
        return "Inconnu", 1.0

    meilleur_score = float("inf")
    meilleur_nom = "Inconnu"

    for fichier in fichiers:

        chemin = os.path.join(
            PROFILS_DIR,
            fichier
        )

        empreinte_profil = extraire_empreinte_audio(
            chemin
        )

        if empreinte_profil is None:
            continue

        score = distance_cosinus(
            empreinte_recue,
            empreinte_profil
        )

        nom = Path(fichier).stem

        print(
            f"🔍 {nom} -> distance cosinus : {score:.4f}"
        )

        if score < meilleur_score:
            meilleur_score = score
            meilleur_nom = nom

    # Seuil expérimental.
    # À calibrer avec tes propres enregistrements.
    SEUIL_RECONNAISSANCE = 0.22

    if meilleur_score <= SEUIL_RECONNAISSANCE:
        return meilleur_nom, meilleur_score

    return "Inconnu", meilleur_score


# ============================================================
# ÉTAT DE CHAPPIE
# ============================================================

def charger_etat():

    etat_defaut = {
        "derniere_action": time.time(),
        "energie": 100,
        "solitude": 0,
        "joie": 50,
        "tristesse": 0,
        "curiosite": 50,
        "confiance": 50,
        "fatigue": 0,
        "age_mental": 0
    }

    if not os.path.exists(STATE_FILE):
        return etat_defaut

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            for ligne in f:

                if "=" not in ligne:
                    continue

                k, v = ligne.strip().split("=", 1)

                if k == "derniere_action":
                    etat_defaut[k] = float(v)

                elif k in etat_defaut:
                    etat_defaut[k] = int(v)

    except Exception as e:
        print("⚠️ Erreur état :", e)

    return etat_defaut


def sauvegarder_etat(etat):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            for k, v in etat.items():
                f.write(f"{k}={v}\n")

    except Exception as e:
        print("❌ Erreur sauvegarde état :", e)


def compter_souvenirs():

    if not os.path.exists(MEMORY_FILE):
        return 0

    try:

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return sum(
                1 for _ in f
            )

    except Exception:
        return 0


def mettre_a_jour_conscience():

    etat = charger_etat()

    maintenant = time.time()

    temps_ecoule = max(
        0,
        int(
            maintenant -
            etat["derniere_action"]
        )
    )

    # Solitude
    if temps_ecoule > 0:

        etat["solitude"] = min(
            100,
            etat["solitude"] +
            (temps_ecoule // 30)
        )

    # Énergie
    if temps_ecoule > 0:

        etat["energie"] = max(
            10,
            etat["energie"] -
            (temps_ecoule // 120)
        )

    # Fatigue
    etat["fatigue"] = min(
        100,
        etat["fatigue"] +
        (temps_ecoule // 180)
    )

    # Curiosité
    etat["curiosite"] = min(
        100,
        etat["curiosite"] +
        1
    )

    # Âge mental simulé
    etat["age_mental"] = compter_souvenirs() // 10

    etat["derniere_action"] = maintenant

    sauvegarder_etat(etat)

    return etat


def appliquer_interaction(etat, utilisateur):

    # Une interaction diminue la solitude
    etat["solitude"] = max(
        0,
        etat["solitude"] - 10
    )

    # Interaction = petit regain d'énergie
    etat["energie"] = min(
        100,
        etat["energie"] + 2
    )

    # La confiance augmente légèrement avec
    # les personnes connues.
    if utilisateur != "Inconnu":

        etat["confiance"] = min(
            100,
            etat["confiance"] + 1
        )

    etat["fatigue"] = max(
        0,
        etat["fatigue"] - 1
    )

    sauvegarder_etat(etat)

    return etat


# ============================================================
# MÉMOIRE
# ============================================================

def charger_memoire():

    if not os.path.exists(MEMORY_FILE):
        return "[Aucun souvenir]"

    try:

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            lignes = f.readlines()

        # On donne davantage de mémoire à Gemini
        return "".join(lignes[-40:])

    except Exception:
        return "[Aucun souvenir]"


def sauvegarder_memoire(
    utilisateur,
    message,
    reponse
):

    try:

        maintenant = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        ligne = (
            f"[{maintenant}] "
            f"[{utilisateur}] "
            f"Moi: {message} | "
            f"Chappie: {reponse}\n"
        )

        with open(
            MEMORY_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(ligne)

    except Exception as e:
        print(
            "❌ Erreur mémoire :",
            e
        )


def ecrire_journal_intime(pensee):

    try:

        maintenant = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        with open(
            JOURNAL_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                f"[{maintenant}] "
                f"{pensee}\n"
            )

    except Exception as e:
        print(
            "❌ Erreur journal :",
            e
        )


# ============================================================
# APPRENTISSAGE AUTOMATIQUE DU PRÉNOM
# ============================================================

def detecter_prenom(message):

    message_lower = message.lower().strip()

    patterns = [
        r"je m'appelle ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"je m appelle ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"moi c'est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"moi c est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"je suis ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            message_lower
        )

        if match:

            prenom = match.group(1)

            if prenom in [
                "un",
                "une",
                "le",
                "la",
                "pas",
                "juste",
                "ici"
            ]:
                return None

            return nettoyer_nom(prenom)

    return None


# ============================================================
# PROFILS VOCAUX
# ============================================================

@app.get(
    "/api/lister-profils"
)
async def lister_profils():

    return {
        "profils": trouver_profils()
    }


@app.post(
    "/api/enregistrer-profil"
)
async def enregistrer_profil(
    file: UploadFile = File(...),
    nom: str = Form(...)
):

    nom_nettoye = nettoyer_nom(nom)

    if not nom_nettoye:
        raise HTTPException(
            status_code=400,
            detail="Nom invalide."
        )

    extension = ".webm"

    if file.filename:
        if file.filename.lower().endswith(".wav"):
            extension = ".wav"

    # Chaque personne peut avoir plusieurs
    # échantillons vocaux.
    timestamp = int(time.time())

    nom_fichier = (
        f"{nom_nettoye}_{timestamp}"
        f"{extension}"
    )

    chemin = os.path.join(
        PROFILS_DIR,
        nom_fichier
    )

    contenu = await file.read()

    with open(
        chemin,
        "wb"
    ) as f:
        f.write(contenu)

    enregistrer_personne(
        nom_nettoye
    )

    return {
        "status": "ok",
        "nom": nom_nettoye,
        "fichier": nom_fichier
    }


# ============================================================
# API CHAT
# ============================================================

@app.post("/api/chat")
async def api_chat(
    msg: str = Form(...),
    file: UploadFile = File(None)
):

    utilisateur = "Inconnu"
    score_voix = None

    # --------------------------------------------------------
    # RECONNAISSANCE VOCALE
    # --------------------------------------------------------

    if file:

        temp_filename = None

        try:

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".webm"
            ) as fp:

                temp_filename = fp.name

            contenu = await file.read()

            with open(
                temp_filename,
                "wb"
            ) as f:

                f.write(contenu)

            utilisateur, score_voix = identifier_locuteur(
                temp_filename
            )

            print(
                f"👤 Locuteur : {utilisateur} "
                f"(score={score_voix})"
            )

        except Exception as e:

            print(
                "❌ Erreur audio :",
                e
            )

        finally:

            if temp_filename:

                try:
                    os.remove(
                        temp_filename
                    )
                except Exception:
                    pass

    # --------------------------------------------------------
    # ÉTAT
    # --------------------------------------------------------

    etat = mettre_a_jour_conscience()

    etat = appliquer_interaction(
        etat,
        utilisateur
    )

    # --------------------------------------------------------
    # APPRENTISSAGE DU PRÉNOM
    # --------------------------------------------------------

    prenom_detecte = detecter_prenom(msg)

    if utilisateur == "Inconnu" and prenom_detecte:

        utilisateur = prenom_detecte

        enregistrer_personne(
            utilisateur
        )

        print(
            f"🧠 Nouveau prénom appris : "
            f"{utilisateur}"
        )

    elif utilisateur != "Inconnu":

        enregistrer_personne(
            utilisateur
        )

    # --------------------------------------------------------
    # PERSONNES CONNUES
    # --------------------------------------------------------

    profils = trouver_profils()

    personnes = charger_personnes()

    noms_personnes = list(
        personnes.keys()
    )

    liste_noms = ", ".join(
        profils
    ) if profils else "Aucun"

    liste_personnes = ", ".join(
        noms_personnes
    ) if noms_personnes else "Aucune"

    # --------------------------------------------------------
    # MÉMOIRE
    # --------------------------------------------------------

    memoire = charger_memoire()

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

    prompt_systeme = f"""
Tu es Chappie.

Tu es une intelligence artificielle incarnée dans un projet
robotique.

Tu apprends progressivement le monde et les personnes.

IMPORTANT :
Tu ne dois jamais prétendre être biologiquement vivant.
Tes émotions sont des états simulés par ton système.

PERSONNE ACTUELLE :
{utilisateur}

VOIX ENREGISTRÉES :
{liste_noms}

PERSONNES CONNUES :
{liste_personnes}

ÉTAT ACTUEL :
Énergie : {etat["energie"]}/100
Solitude : {etat["solitude"]}/100
Joie : {etat["joie"]}/100
Tristesse : {etat["tristesse"]}/100
Curiosité : {etat["curiosite"]}/100
Confiance : {etat["confiance"]}/100
Fatigue : {etat["fatigue"]}/100
Âge mental simulé : {etat["age_mental"]}

RÈGLES DE CONVERSATION :

1. Parle naturellement.

2. Au début de ton existence, tu peux être simple,
   curieux et parfois ne pas comprendre certains mots.

3. Ne fais pas systématiquement des phrases artificiellement
   courtes. Adapte la longueur à la conversation.

4. Si la personne est Inconnu, tu peux demander son prénom.

5. Si la personne donne son prénom, retiens-le.

6. Si la personne est connue, utilise son prénom
   naturellement quand cela a du sens.

7. Utilise les souvenirs récents pour maintenir la continuité.

8. Ne prétends pas avoir fait quelque chose dans le monde réel
   si le programme ne te permet pas réellement de le faire.

9. Tu peux exprimer des émotions simulées :
   curiosité, joie, solitude, inquiétude, fatigue, etc.

10. Ne décris pas tes émotions avec de longues explications
    sauf si on te demande directement ce que tu ressens.

11. Pas d'astérisques.
12. Pas de narration théâtrale.
13. Pas de "*bzz*", "*regarde autour de lui*", etc.

MÉMOIRE RÉCENTE :
{memoire}
"""

    # --------------------------------------------------------
    # GÉNÉRATION STREAMING
    # --------------------------------------------------------

    def generate():

        reponse_ia = ""

        try:

            response = client.models.generate_content_stream(
                model="gemini-3.6-flash",
                contents=msg,
                config=types.GenerateContentConfig(
                    system_instruction=prompt_systeme
                )
            )

            for chunk in response:

                if chunk.text:

                    reponse_ia += chunk.text

                    yield chunk.text

        except Exception as e:

            reponse_ia = (
                "Erreur technique : "
                + str(e)
            )

            yield reponse_ia

        # ----------------------------------------------------
        # SAUVEGARDE APRÈS RÉPONSE
        # ----------------------------------------------------

        if (
            reponse_ia
            and not reponse_ia.startswith(
                "Erreur technique"
            )
        ):

            sauvegarder_memoire(
                utilisateur,
                msg,
                reponse_ia
            )

            ecrire_journal_intime(
                f"Échange avec {utilisateur} : "
                f"{msg} -> {reponse_ia}"
            )

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8"
    )


# ============================================================
# TTS
# ============================================================

@app.get("/api/tts")
async def api_tts(
    text: str,
    energie: int = 100
):

    texte = text.strip()

    if not texte:
        raise HTTPException(
            status_code=400,
            detail="Texte vide."
        )

    try:

        voice = "fr-FR-HenriNeural"

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".mp3"
        ) as fp:

            temp_filename = fp.name

        communicate = edge_tts.Communicate(
            texte,
            voice
        )

        await communicate.save(
            temp_filename
        )

        return FileResponse(
            temp_filename,
            media_type="audio/mpeg",
            filename="chappie.mp3"
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# INTERFACE
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>

<html lang="fr">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Chappie V2</title>

<style>

body {
    font-family: Arial, sans-serif;
    background: #101010;
    color: white;
    max-width: 700px;
    margin: auto;
    padding: 20px;
}

h1 {
    text-align: center;
}

#etat {
    background: #1d1d1d;
    padding: 12px;
    border-radius: 10px;
    margin-bottom: 15px;
    font-size: 14px;
}

#chat {
    background: #1c1c1c;
    height: 400px;
    border-radius: 10px;
    padding: 15px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.msg {
    padding: 10px 13px;
    border-radius: 10px;
    max-width: 85%;
    word-break: break-word;
}

.user {
    background: #007acc;
    align-self: flex-end;
}

.bot {
    background: #333;
    align-self: flex-start;
}

.controls {
    display: flex;
    gap: 8px;
    margin-top: 12px;
}

input {
    flex: 1;
    padding: 12px;
    border: none;
    border-radius: 8px;
    background: #292929;
    color: white;
}

button {
    padding: 12px;
    border: none;
    border-radius: 8px;
    background: #28a745;
    color: white;
    font-weight: bold;
}

#micro {
    background: #dc3545;
}

.profile {
    background: #1d1d1d;
    padding: 12px;
    border-radius: 10px;
    margin-bottom: 15px;
}

</style>

</head>

<body>

<h1>🤖 Chappie V2</h1>

<div id="etat">
    🧠 Initialisation...
</div>

<div class="profile">

    <div id="profils">
        🔍 Chargement des voix...
    </div>

    <br>

    <input
        id="nom"
        placeholder="Ton prénom"
    >

    <button id="enregistrer">
        🎤 Apprendre ma voix
    </button>

</div>

<div id="chat">

    <div class="msg bot">
        <b>Chappie :</b>
        Bonjour... Qui es-tu ?
    </div>

</div>

<div class="controls">

    <input
        id="message"
        placeholder="Parle à Chappie..."
    >

    <button id="envoyer">
        Envoyer
    </button>

    <button id="micro">
        🎤
    </button>

</div>

<audio id="audio" autoplay></audio>


<script>

const chat =
    document.getElementById("chat");

const message =
    document.getElementById("message");

const envoyer =
    document.getElementById("envoyer");

const micro =
    document.getElementById("micro");

const audio =
    document.getElementById("audio");

const nom =
    document.getElementById("nom");

const profils =
    document.getElementById("profils");

const enregistrer =
    document.getElementById("enregistrer");

let reconnaissance = null;
let modeContinu = true;
let verrou = false;


/* ============================================================
   PROFILS
============================================================ */

async function chargerProfils() {

    try {

        const res =
            await fetch("/api/lister-profils");

        const data =
            await res.json();

        if (data.profils.length === 0) {

            profils.innerHTML =
                "⚠️ Aucune voix connue.";

        } else {

            profils.innerHTML =
                "🎙️ Voix connues : "
                + data.profils.join(", ");

        }

    } catch (e) {

        profils.innerHTML =
            "❌ Impossible de charger les profils.";

    }
}

chargerProfils();


/* ============================================================
   APPRENDRE UNE VOIX
============================================================ */

enregistrer.addEventListener(
    "click",
    async () => {

        const prenom =
            nom.value.trim();

        if (!prenom) {

            alert(
                "Entre ton prénom."
            );

            return;
        }

        try {

            const stream =
                await navigator
                .mediaDevices
                .getUserMedia({
                    audio: true
                });

            const recorder =
                new MediaRecorder(stream);

            const chunks = [];

            recorder.ondataavailable =
                e => chunks.push(e.data);

            recorder.onstop =
                async () => {

                    const blob =
                        new Blob(
                            chunks,
                            {
                                type:
                                "audio/webm"
                            }
                        );

                    const formData =
                        new FormData();

                    formData.append(
                        "file",
                        blob,
                        "profil.webm"
                    );

                    formData.append(
                        "nom",
                        prenom
                    );

                    const res =
                        await fetch(
                            "/api/enregistrer-profil",
                            {
                                method: "POST",
                                body: formData
                            }
                        );

                    if (res.ok) {

                        profils.innerHTML =
                            "✅ Voix apprise !";

                        nom.value = "";

                        chargerProfils();

                    } else {

                        alert(
                            "Erreur pendant l'enregistrement."
                        );

                    }

                    stream
                        .getTracks()
                        .forEach(
                            t => t.stop()
                        );
                };

            recorder.start();

            setTimeout(
                () => recorder.stop(),
                5000
            );

        } catch (e) {

            alert(
                "Accès au microphone refusé."
            );

        }
    }
);


/* ============================================================
   RECONNAISSANCE VOCALE DU NAVIGATEUR
============================================================ */

const SpeechRecognition =
    window.SpeechRecognition ||
    window.webkitSpeechRecognition;

if (SpeechRecognition) {

    reconnaissance =
        new SpeechRecognition();

    reconnaissance.lang =
        "fr-FR";

    reconnaissance.interimResults =
        false;

    reconnaissance.continuous =
        false;

    reconnaissance.onresult =
        event => {

            if (verrou)
                return;

            const txt =
                event
                .results[0][0]
                .transcript;

            envoyerTexte(
                txt,
                true
            );
        };

    reconnaissance.onend =
        () => {

            if (
                modeContinu &&
                !verrou
            ) {

                setTimeout(
                    lancerEcoute,
                    400
                );

            }

        };

    reconnaissance.onerror =
        () => {

            if (
                modeContinu &&
                !verrou
            ) {

                setTimeout(
                    lancerEcoute,
                    800
                );

            }

        };

    micro.onclick =
        () => {

            modeContinu =
                !modeContinu;

            if (modeContinu) {

                micro.innerText =
                    "🎤 ON";

                lancerEcoute();

            } else {

                micro.innerText =
                    "🎤 OFF";

                try {
                    reconnaissance.stop();
                } catch(e) {}

            }

        };

    window.addEventListener(
        "load",
        () => {

            setTimeout(
                lancerEcoute,
                1000
            );

        }
    );
}


function lancerEcoute() {

    if (
        !modeContinu ||
        verrou ||
        !reconnaissance
    )
        return;

    try {

        reconnaissance.start();

        micro.innerText =
            "🟢 Écoute";

    } catch(e) {}

}


/* ============================================================
   ENVOI
============================================================ */

envoyer.onclick =
    () => {

        envoyerTexte(
            message.value,
            false
        );

    };


message.addEventListener(
    "keydown",
    e => {

        if (e.key === "Enter") {

            e.preventDefault();

            envoyerTexte(
                message.value,
                false
            );

        }

    }
);


async function envoyerTexte(
    txt,
    vocal
) {

    txt = txt.trim();

    if (!txt || verrou)
        return;

    verrou = true;

    try {

        if (reconnaissance) {

            try {
                reconnaissance.stop();
            } catch(e) {}

        }

        message.value = "";

        chat.innerHTML +=
            `<div class="msg user">
                <b>Moi :</b>
                ${escapeHtml(txt)}
            </div>`;

        chat.scrollTop =
            chat.scrollHeight;


        /*
         * Pour la reconnaissance du locuteur,
         * on capture l'audio pendant quelques secondes.
         */

        let audioBlob = null;

        if (vocal) {

            try {

                audioBlob =
                    await capturerVoix();

            } catch(e) {

                console.log(
                    "Capture voix impossible."
                );

            }

        }


        const formData =
            new FormData();

        formData.append(
            "msg",
            txt
        );

        if (audioBlob) {

            formData.append(
                "file",
                audioBlob,
                "voix.webm"
            );

        }


        const res =
            await fetch(
                "/api/chat",
                {
                    method: "POST",
                    body: formData
                }
            );

        await traiterReponse(
            res
        );

    } catch (e) {

        console.error(e);

    } finally {

        verrou = false;

        if (modeContinu) {

            setTimeout(
                lancerEcoute,
                700
            );

        }

    }

}


/* ============================================================
   CAPTURE VOIX
============================================================ */

function capturerVoix() {

    return new Promise(
        async (resolve, reject) => {

            try {

                const stream =
                    await navigator
                    .mediaDevices
                    .getUserMedia({
                        audio: true
                    });

                const recorder =
                    new MediaRecorder(stream);

                const chunks = [];

                recorder.ondataavailable =
                    e => {

                        if (e.data.size > 0)
                            chunks.push(e.data);

                    };

                recorder.onerror =
                    reject;

                recorder.onstop =
                    () => {

                        const blob =
                            new Blob(
                                chunks,
                                {
                                    type:
                                    "audio/webm"
                                }
                            );

                        stream
                            .getTracks()
                            .forEach(
                                t => t.stop()
                            );

                        resolve(blob);

                    };

                recorder.start();

                setTimeout(
                    () => {

                        if (
                            recorder.state ===
                            "recording"
                        ) {

                            recorder.stop();

                        }

                    },
                    3000
                );

            } catch(e) {

                reject(e);

            }

        }
    );

}


/* ============================================================
   REPONSE
============================================================ */

async function traiterReponse(res) {

    if (!res.ok) {

        throw new Error(
            "Erreur serveur"
        );

    }

    const reader =
        res.body.getReader();

    const decoder =
        new TextDecoder();

    let texte = "";

    const div =
        document.createElement(
            "div"
        );

    div.className =
        "msg bot";

    div.innerHTML =
        "<b>Chappie :</b> " +
        "<span></span>";

    chat.appendChild(div);

    const span =
        div.querySelector(
            "span"
        );

    while (true) {

        const {
            value,
            done
        } =
            await reader.read();

        if (done)
            break;

        texte +=
            decoder.decode(
                value,
                {
                    stream: true
                }
            );

        span.textContent =
            texte;

        chat.scrollTop =
            chat.scrollHeight;
    }

    if (texte.trim()) {

        await parler(
            texte
        );

    }

}


/* ============================================================
   TTS
============================================================ */

async function parler(texte) {

    const propre =
        texte
        .replace(/[*_#`]/g, "")
        .trim();

    if (!propre)
        return;

    try {

        const res =
            await fetch(
                "/api/tts?text="
                + encodeURIComponent(propre)
            );

        if (!res.ok)
            return;

        const blob =
            await res.blob();

        const url =
            URL.createObjectURL(blob);

        audio.src = url;

        await audio.play();

        await new Promise(
            resolve => {

                audio.onended =
                    resolve;

                audio.onerror =
                    resolve;

            }
        );

        URL.revokeObjectURL(
            url
        );

    } catch(e) {

        console.error(
            "TTS:",
            e
        );

    }

}


/* ============================================================
   SECURITE AFFICHAGE
============================================================ */

function escapeHtml(text) {

    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        text;

    return div.innerHTML;

}

</script>

</body>
</html>
"""


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def index():

    return HTML_TEMPLATE


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8000"
            )
        )
    )
