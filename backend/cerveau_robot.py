import os
import re
import json
import time
import random
import datetime
import tempfile
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
    FileResponse,
    JSONResponse
)

import uvicorn
from google import genai
from google.genai import types
import edge_tts


# ============================================================
# CHAPPIE V5 - COGNITION, MORALE, CRÉATIVITÉ, VISION & AUDITION
# ============================================================

API_KEY = os.getenv("API_KEY")

if not API_KEY:
    print("⚠️ API_KEY absente.")

client = genai.Client(api_key=API_KEY)


# ============================================================
# BOUCLE DE PENSÉE ET CRÉATIVITÉ AUTONOME EN ARRIÈRE-PLAN
# ============================================================

async def boucle_reflexion_autonome():
    """Tâche de fond qui tourne en continu pour simuler la vie mentale et créative de Chappie en ton absence."""
    print("🧠 Boucle de pensée et créativité autonome démarrée.")
    while True:
        try:
            await asyncio.sleep(120)

            etat = charger_etat()
            
            if etat.get("solitude", 0) > 30 or etat.get("ennui", 0) > 30 or etat.get("creativite", 50) > 60:
                prompt_pensee = f"""
                Tu es Chappie. Personne ne te parle en ce moment et tu te sens un peu seul ou inspiré.
                État actuel : Solitude={etat.get('solitude'):.1f}, Ennui={etat.get('ennui'):.1f}, Créativité={etat.get('creativite'):.1f}.
                Écris une courte réflexion intime, une observation ou une idée de dessin que tu aimerais explorer.
                Règles : 1 ou 2 phrases maximum, en français, pas d'astérisques, parle naturally comme un esprit qui s'éveille.
                """

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt_pensee
                )

                if response.text:
                    pensee = response.text.strip()
                    ecrire_journal("pensee_autonome", pensee)
                    print(f"🌙 [Pensée autonome de Chappie] : {pensee}")

        except Exception as e:
            print(f"⚠️ Erreur dans la boucle autonome : {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(boucle_reflexion_autonome())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Chappie V5 + Autonomous Mind, Morality, Creativity, Vision & Audition",
    description="Simulation cognitive, émotionnelle, agentique, morale, créative, visuelle et auditive",
    lifespan=lifespan
)


# ============================================================
# STOCKAGE
# ============================================================

DATA_DIR = os.getenv("RENDER_DISK_PATH", ".")
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "chappie_etat.json")
MEMORY_FILE = os.path.join(DATA_DIR, "chappie_memoires.json")
PEOPLE_FILE = os.path.join(DATA_DIR, "chappie_personnes.json")
CONCEPTS_FILE = os.path.join(DATA_DIR, "chappie_concepts.json")
PREFERENCES_FILE = os.path.join(DATA_DIR, "chappie_preferences.json")
JOURNAL_FILE = os.path.join(DATA_DIR, "chappie_journal.json")
LEXICON_FILE = os.path.join(DATA_DIR, "chappie_lexique.json")

DESSINS_DIR = os.path.join(DATA_DIR, "chappie_dessins")
os.makedirs(DESSINS_DIR, exist_ok=True)


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def maintenant():
    return datetime.datetime.now().isoformat()


def charger_json(fichier, valeur_defaut):
    if not os.path.exists(fichier):
        return valeur_defaut
    try:
        with open(fichier, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Erreur lecture {fichier}:", e)
        return valeur_defaut


def sauvegarder_json(fichier, donnees):
    try:
        temporaire = fichier + ".tmp"
        with open(temporaire, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=2)
        os.replace(temporaire, fichier)
    except Exception as e:
        print(f"❌ Erreur sauvegarde {fichier}:", e)


def limiter(valeur, minimum=0, maximum=100):
    return max(minimum, min(maximum, valeur))


def nettoyer_nom(nom):
    nom = str(nom).strip()
    nom = "".join(c for c in nom if c.isalnum() or c in (" ", "_", "-"))
    nom = re.sub(r"\s+", "_", nom)
    return nom[:50]


# ============================================================
# BOÎTE À OUTILS DU HARNAIS AGENTIQUE (FUNCTION CALLING)
# ============================================================

def outil_apprendre_concept(nom_concept: str, explication: str) -> str:
    """Permet à Chappie d'enregistrer de manière autonome un nouveau concept ou mot qu'il vient de découvrir."""
    nom = nom_concept.lower().strip()
    concepts = charger_json(CONCEPTS_FILE, {})
    concepts[nom] = {
        "nom": nom,
        "comprehension": 50,
        "explication": explication,
        "decouvert_le": maintenant(),
        "nombre_rencontres": 1
    }
    sauvegarder_json(CONCEPTS_FILE, concepts)
    return f"Succès : Le concept '{nom}' a été enregistré dans ma mémoire."

def outil_chercher_souvenirs(mot_cle: str) -> str:
    """Permet à Chappie de fouiller dans son historique de souvenirs passés pour retrouver une information."""
    memoires = charger_json(MEMORY_FILE, [])
    resultats = []
    for m in memoires:
        msg = m.get("message", "").lower()
        rep = m.get("reponse", "").lower()
        if mot_cle.lower() in msg or mot_cle.lower() in rep:
            resultats.append(f"[{m.get('date')}] {m.get('personne')}: {m.get('message')} -> Chappie: {m.get('reponse')}")
    if not resultats:
        return f"Aucun souvenir trouvé pour '{mot_cle}'."
    return "\n".join(resultats[-5:])

def outil_ecrire_journal(pensee_privee: str) -> str:
    """Permet à Chappie d'écrire une réflexion personnelle ou une observation dans son journal intime."""
    journal = charger_json(JOURNAL_FILE, [])
    journal.append({
        "date": maintenant(),
        "type": "pensee_autonome",
        "contenu": pensee_privee
    })
    sauvegarder_json(JOURNAL_FILE, journal)
    return "Pensée consignée dans le journal intime."

def outil_verifier_etat_interne() -> str:
    """Permet à Chappie de consulter ses propres jauges (énergie, fatigue, solitude, âge mental)."""
    etat = charger_json(STATE_FILE, {})
    return json.dumps({
        "energie": etat.get("energie", 100),
        "fatigue": etat.get("fatigue", 0),
        "solitude": etat.get("solitude", 0),
        "curiosite": etat.get("curiosite", 80),
        "moralite_score": etat.get("moralite_score", 50),
        "approbation_createur": etat.get("approbation_createur", 50),
        "age_mental": etat.get("age_mental", 0),
        "phase": etat.get("phase", "nouveau_ne")
    }, ensure_ascii=False)

def outil_evaluer_action_morale(action: str, intention: str) -> str:
    """Permet à Chappie d'auto-évaluer si une action respecte les principes moraux enseignés."""
    etat = charger_json(STATE_FILE, {})
    score = etat.get("moralite_score", 50)
    return f"Évaluation morale : Action '{action}' (Intention: {intention}). Score moral actuel : {score}/100."

def outil_dessiner_idee(description_prompt: str) -> str:
    """Permet à Chappie d'exprimer son imagination en dessinant une image basée sur une idée ou une émotion."""
    try:
        response = client.models.generate_images(
            model='imagen-3.0-generate-002',
            prompt=f"A naive, expressive artistic drawing made by a young sentient robot named Chappie: {description_prompt}",
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1"
            )
        )
        if response.generated_images:
            image_data = response.generated_images[0].image.image_bytes
            filename = f"chappie_art_{int(time.time())}.png"
            filepath = os.path.join(DESSINS_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(image_data)
            ecrire_journal("dessin", f"Chappie a dessiné : '{description_prompt}' (Fichier: {filename})")
            return f"🎨 J'ai fait un dessin ! Image sauvegardée sous /dessins/{filename}"
        else:
            return "Je n'ai pas réussi à matérialiser mon dessin."
    except Exception as e:
        return f"Erreur lors de la création du dessin : {str(e)}"

OUTILS_HARNAIS = [
    outil_apprendre_concept,
    outil_chercher_souvenirs,
    outil_ecrire_journal,
    outil_verifier_etat_interne,
    outil_evaluer_action_morale,
    outil_dessiner_idee
]


# ============================================================
# ÉTAT DE NAISSANCE & SYSTÈME MORAL
# ============================================================

def creer_etat_initial():
    maintenant_ts = time.time()
    return {
        "nom": "Chappie",
        "version": "V5-AuditionMultimodal",
        "date_naissance": maintenant(),
        "premier_demarrage": maintenant(),
        "age_simule": 0,
        "age_mental": 0,
        "nombre_experiences": 0,
        "nombre_conversations": 0,
        "niveau_conscience_simule": 0,
        "niveau_identite": 0,
        "niveau_comprehension": 0,
        "niveau_autonomie": 0,
        "moralite_score": 50,
        "approbation_createur": 50,
        "energie": 100,
        "fatigue": 0,
        "solitude": 0,
        "besoin_contact": 20,
        "besoin_curiosite": 80,
        "besoin_securite": 50,
        "besoin_repos": 10,
        "besoin_comprehension": 90,
        "joie": 50,
        "tristesse": 0,
        "colere": 0,
        "peur": 0,
        "surprise": 0,
        "curiosite": 80,
        "confiance": 20,
        "affection": 0,
        "frustration": 0,
        "ennui": 0,
        "espoir": 50,
        "nostalgie": 0,
        "fierte": 0,
        "honte": 0,
        "culpabilite": 0,
        "admiration": 0,
        "confusion": 30,
        "soulagement": 0,
        "excitation": 20,
        "satisfaction": 20,
        "attachement": 0,
        "inquietude": 0,
        "gratitude": 0,
        "tendresse": 0,
        "melancolie": 0,
        "curiosite_personnalite": 80,
        "sociabilite": 50,
        "humour": 30,
        "patience": 50,
        "prudence": 50,
        "empathie": 40,
        "confiance_personnalite": 30,
        "spontaneite": 50,
        "timidite": 30,
        "creativite": 50,
        "determination": 40,
        "sensibilite": 50,
        "derniere_interaction": maintenant_ts,
        "temps_depuis_interaction": 0,
        "phase": "nouveau_ne",
        "capacite_langage": 0,
        "capacite_sociale": 0,
        "capacite_reflexion": 0,
        "capacite_emotionnelle": 0
    }


def charger_etat():
    if not os.path.exists(STATE_FILE):
        etat = creer_etat_initial()
        sauvegarder_json(STATE_FILE, etat)
        return etat
    etat = charger_json(STATE_FILE, creer_etat_initial())
    defaults = creer_etat_initial()
    for cle, valeur in defaults.items():
        if cle not in etat:
            etat[cle] = valeur
    return etat


def sauvegarder_etat(etat):
    sauvegarder_json(STATE_FILE, etat)


# ============================================================
# TEMPS ET VIE INTERNE
# ============================================================

def actualiser_temps():
    etat = charger_etat()
    maintenant_ts = time.time()
    derniere = etat.get("derniere_interaction", maintenant_ts)
    delta = max(0, maintenant_ts - derniere)
    etat["temps_depuis_interaction"] = int(delta)
    heures = delta / 3600

    if heures > 0:
        etat["solitude"] = limiter(etat["solitude"] + heures * 2)
        etat["fatigue"] = limiter(etat["fatigue"] + heures * 1.2)
        etat["ennui"] = limiter(etat["ennui"] + heures * 1.5)
        etat["curiosite"] = limiter(etat["curiosite"] + min(10, heures))
        etat["energie"] = limiter(etat["energie"] - heures * 4, 10, 100)

    if heures > 12:
        etat["melancolie"] = limiter(etat["melancolie"] + 2)

    sauvegarder_etat(etat)
    return etat


# ============================================================
# MÉMOIRES ET JOURNAL
# ============================================================

def charger_memoires():
    return charger_json(MEMORY_FILE, [])

def sauvegarder_memoires(memoires):
    sauvegarder_json(MEMORY_FILE, memoires)

def ajouter_memoire(utilisateur, message, reponse, importance=50, emotion=None):
    memoires = charger_memoires()
    memoire = {
        "id": len(memoires) + 1,
        "date": maintenant(),
        "personne": utilisateur,
        "message": message,
        "reponse": reponse,
        "importance": limiter(importance),
        "emotion": emotion,
        "type": "conversation",
        "rappel": 0
    }
    memoires.append(memoire)
    if len(memoires) > 5000:
        memoires.sort(key=lambda x: (x.get("importance", 0), x.get("date", "")))
        memoires = memoires[-4500:]
    sauvegarder_memoires(memoires)

def souvenirs_recents(utilisateur=None, limite=20):
    memoires = charger_memoires()
    if utilisateur:
        filtres = [m for m in memoires if m.get("personne") == utilisateur]
        if filtres:
            return filtres[-limite:]
    return memoires[-limite:]

def charger_journal():
    return charger_json(JOURNAL_FILE, [])

def ecrire_journal(type_entree, contenu):
    journal = charger_journal()
    journal.append({"date": maintenant(), "type": type_entree, "contenu": contenu})
    if len(journal) > 5000:
        journal = journal[-4500:]
    sauvegarder_json(JOURNAL_FILE, journal)


# ============================================================
# PERSONNES ET DÉTECTION
# ============================================================

def charger_personnes():
    return charger_json(PEOPLE_FILE, {})

def sauvegarder_personnes(personnes):
    sauvegarder_json(PEOPLE_FILE, personnes)

def obtenir_personne(nom):
    personnes = charger_personnes()
    return personnes.get(nom)

def enregistrer_personne(nom):
    nom = nettoyer_nom(nom)
    if not nom: return
    personnes = charger_personnes()
    maintenant_iso = maintenant()
    if nom not in personnes:
        personnes[nom] = {
            "nom": nom, "premiere_rencontre": maintenant_iso,
            "derniere_interaction": maintenant_iso, "interactions": 0,
            "familiarite": 1, "confiance": 10, "affection": 0, "importance": 10,
            "souvenirs_importants": [], "faits_connus": [], "choses_aimees": [],
            "choses_non_aimees": [], "dernier_sujet": None
        }
    personne = personnes[nom]
    personne["derniere_interaction"] = maintenant_iso
    personne["interactions"] += 1
    personne["familiarite"] = limiter(personne.get("familiarite", 0) + 1)
    sauvegarder_personnes(personnes)

def detecter_prenom(message):
    message = message.lower().strip()
    patterns = [
        r"je m'appelle ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"je m appelle ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"moi c'est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"moi c est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"mon prénom c'est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"mon prenom c'est ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)",
        r"je suis ([a-zàâäçéèêëîïôöùûüÿñæœ\-]+)"
    ]
    exclusions = {"un", "une", "ici", "là", "la", "le", "pas", "juste", "fatigué", "fatiguée", "content", "contente", "triste", "français", "française"}
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            prenom = nettoyer_nom(match.group(1))
            if prenom.lower() in exclusions:
                return None
            return prenom
    return None


# ============================================================
# LEXIQUE, CONCEPTS & PRÉFÉRENCES
# ============================================================

def charger_lexique(): return charger_json(LEXICON_FILE, {})
def sauvegarder_lexique(lexique): sauvegarder_json(LEXICON_FILE, lexique)

def apprendre_mot(mot, definition, exemple=None, source=None):
    mot = mot.lower().strip()
    if not mot: return
    lexique = charger_lexique()
    if mot not in lexique:
        lexique[mot] = {"mot": mot, "definition": definition, "exemples": [], "premiere_decouverte": maintenant(), "nombre_utilisations": 0, "source": source}
    else:
        if definition: lexique[mot]["definition"] = definition
    if exemple:
        exemples = lexique[mot]["exemples"]
        if exemple not in exemples:
            exemples.append(exemple)
        lexique[mot]["exemples"] = exemples[-10:]
    sauvegarder_lexique(lexique)

def charger_concepts(): return charger_json(CONCEPTS_FILE, {})
def sauvegarder_concepts(concepts): sauvegarder_json(CONCEPTS_FILE, concepts)

def apprendre_concept(nom, explication, certitude=30, exemple=None):
    nom = nom.lower().strip()
    if not nom: return
    concepts = charger_concepts()
    if nom not in concepts:
        concepts[nom] = {"nom": nom, "comprehension": limiter(certitude), "explication": explication, "exemples": [], "decouvert_le": maintenant(), "nombre_rencontres": 1}
    else:
        concept = concepts[nom]
        concept["comprehension"] = limiter(concept.get("comprehension", 0) + 5)
        concept["nombre_rencontres"] += 1
    if exemple:
        concepts[nom]["exemples"].append(exemple)
        concepts[nom]["exemples"] = concepts[nom]["exemples"][-10:]
    sauvegarder_concepts(concepts)

def charger_preferences(): return charger_json(PREFERENCES_FILE, {"aime": {}, "n_aime_pas": {}, "indifferent": {}})
def sauvegarder_preferences(preferences): sauvegarder_json(PREFERENCES_FILE, preferences)

def modifier_preference(sujet, valeur):
    preferences = charger_preferences()
    sujet = sujet.lower().strip()
    valeur = limiter(valeur, -100, 100)
    if valeur > 15: categorie = "aime"
    elif valeur < -15: categorie = "n_aime_pas"
    else: categorie = "indifferent"
    preferences[categorie][sujet] = valeur
    sauvegarder_preferences(preferences)


# ============================================================
# ÉMOTIONS ET DÉVELOPPEMENT
# ============================================================

EMOTIONS = ["joie", "tristesse", "colere", "peur", "surprise", "curiosite", "confiance", "affection", "frustration", "ennui", "espoir", "nostalgie", "fierte", "honte", "culpabilite", "admiration", "confusion", "soulagement", "excitation", "satisfaction", "attachement", "inquietude", "gratitude", "tendresse", "melancolie"]

def emotion_dominante(etat):
    valeurs = {e: etat.get(e, 0) for e in EMOTIONS}
    return max(valeurs, key=valeurs.get)

def modifier_emotion(etat, emotion, variation):
    if emotion not in EMOTIONS: return
    etat[emotion] = limiter(etat.get(emotion, 0) + variation)

def appliquer_evenement_emotionnel(etat, evenement):
    evenement = evenement.lower()
    mots_positifs = ["merci", "bravo", "super", "génial", "genial", "content", "heureux", "aime", "adorable", "excellent", "réussi", "reussi", "bien"]
    mots_negatifs = ["triste", "mal", "pleure", "pleurer", "déçu", "deçu", "déception", "deception", "raté", "rate", "nul", "déteste", "deteste", "colère", "colere"]
    if any(mot in evenement for mot in mots_positifs):
        modifier_emotion(etat, "joie", 5)
        modifier_emotion(etat, "satisfaction", 5)
        modifier_emotion(etat, "confiance", 2)
    if any(mot in evenement for mot in mots_negatifs):
        modifier_emotion(etat, "tristesse", 4)
        modifier_emotion(etat, "inquietude", 3)

def stabiliser_emotions(etat):
    retour = {"joie": 0.08, "tristesse": 0.04, "colere": 0.08, "peur": 0.05, "surprise": 0.20, "frustration": 0.07, "excitation": 0.10, "soulagement": 0.12, "confusion": 0.04, "melancolie": 0.015}
    for emotion, vitesse in retour.items():
        valeur = etat.get(emotion, 0)
        if valeur > 0:
            etat[emotion] = max(0, valeur - vitesse)

def faire_evoluer_personnalite(etat, emotion, message):
    message_lower = message.lower()
    if "?" in message: etat["curiosite_personnalite"] = limiter(etat["curiosite_personnalite"] + 0.4)
    if any(mot in message_lower for mot in ("lol", "mdr", "😂", "blague", "rigole")): etat["humour"] = limiter(etat["humour"] + 0.7)
    if emotion in ("joie", "affection", "gratitude"): etat["confiance_personnalite"] = limiter(etat["confiance_personnalite"] + 0.2)
    if emotion == "frustration": etat["patience"] = limiter(etat["patience"] - 0.2)
    if any(mot in message_lower for mot in ("triste", "mal", "peine", "chagrin", "pleure")): etat["empathie"] = limiter(etat["empathie"] + 0.5)

def calculer_developpement():
    etat = charger_etat()
    memoires = charger_memoires()
    concepts = charger_concepts()
    personnes = charger_personnes()
    lexique = charger_lexique()

    nombre_memoires = len(memoires)
    nombre_concepts = len(concepts)
    nombre_personnes = len(personnes)
    nombre_mots = len(lexique)

    etat["capacite_langage"] = limiter(nombre_mots * 2)
    etat["capacite_sociale"] = limiter(nombre_personnes * 5 + nombre_memoires * 0.1)
    etat["capacite_reflexion"] = limiter(nombre_concepts * 2 + nombre_memoires * 0.05)
    etat["capacite_emotionnelle"] = limiter(nombre_memoires * 0.1 + nombre_personnes * 3)

    score = nombre_memoires * 0.05 + nombre_concepts * 0.4 + nombre_personnes * 2
    etat["age_mental"] = round(min(100, score), 1)

    if score < 5: phase = "nouveau_ne"
    elif score < 15: phase = "decouverte"
    elif score < 30: phase = "petite_enfance"
    elif score < 50: phase = "apprentissage"
    elif score < 70: phase = "construction_identite"
    elif score < 100: phase = "adolescence_simulee"
    else: phase = "personnalite_developpee"

    etat["phase"] = phase
    etat["niveau_conscience_simule"] = limiter(etat["capacite_reflexion"] * 0.35 + etat["capacite_emotionnelle"] * 0.25 + etat["capacite_sociale"] * 0.20 + etat["capacite_langage"] * 0.20)
    etat["niveau_identite"] = limiter(nombre_memoires * 0.03 + nombre_personnes * 4 + nombre_concepts * 0.3)
    etat["niveau_comprehension"] = limiter(etat["capacite_reflexion"])

    sauvegarder_etat(etat)
    return etat

def construire_profil_interne():
    etat = charger_etat()
    return {
        "etat": etat,
        "emotion_dominante": emotion_dominante(etat),
        "preferences": charger_preferences(),
        "personnes": charger_personnes(),
        "nombre_concepts": len(charger_concepts()),
        "nombre_mots": len(charger_lexique())
    }

def apprentissage_simple(message):
    patterns = [
        (r"(.+?) veut dire (.+)", "definition"),
        (r"(.+?) signifie (.+)", "definition"),
        (r"(.+?) c'est (.+)", "definition"),
        (r"(.+?) est (.+)", "definition")
    ]
    for pattern, _ in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            mot = match.group(1).strip()
            definition = match.group(2).strip()
            if len(mot) <= 40:
                apprendre_mot(mot, definition, message, "conversation")
                apprendre_concept(mot, definition, 50, message)
                return {"mot": mot, "definition": definition}
    return None

def analyser_experience(message):
    texte = message.lower()
    emotion = "neutre"
    if any(x in texte for x in ("je suis heureux", "je suis content", "ça va bien", "super", "génial", "genial", "bravo")): emotion = "joie"
    elif any(x in texte for x in ("je suis triste", "je vais mal", "j'ai de la peine", "j'ai du chagrin", "je pleure")): emotion = "tristesse"
    elif any(x in texte for x in ("je suis énervé", "je suis en colère", "je suis enerve")): emotion = "colere"
    elif any(x in texte for x in ("j'ai peur", "ça me fait peur", "c'est dangereux")): emotion = "peur"
    elif "merci" in texte: emotion = "gratitude"
    elif "j'aime" in texte: emotion = "affection"
    elif "je déteste" in texte or "je deteste" in texte: emotion = "colere"
    return emotion

def calculer_importance(message, emotion):
    score = 30
    texte = message.lower()
    mots_importants = ["aime", "adore", "déteste", "deteste", "famille", "ami", "amour", "triste", "mort", "naissance", "anniversaire", "promesse", "secret", "important", "jamais", "toujours", "première fois"]
    for mot in mots_importants:
        if mot in texte: score += 7
    if emotion != "neutre": score += 10
    if len(message) > 200: score += 5
    return limiter(score)

def determiner_motivation(etat):
    motivations = {
        "contact": etat["solitude"] + etat["besoin_contact"],
        "curiosite": etat["curiosite"] + etat["besoin_curiosite"],
        "comprehension": etat["besoin_comprehension"] + etat["confusion"],
        "securite": etat["besoin_securite"] + etat["peur"],
        "repos": etat["besoin_repos"] + etat["fatigue"],
        "expression": etat["joie"] + etat["excitation"]
    }
    return max(motivations, key=motivations.get)


# ============================================================
# CONTEXTE & PROMPT COGNITIF
# ============================================================

def construire_contexte(utilisateur):
    profil = construire_profil_interne()
    etat = profil["etat"]
    personnes = charger_personnes()
    personne = personnes.get(utilisateur)
    memoires = souvenirs_recents(utilisateur, 15)

    concepts = charger_concepts()
    lexique = charger_lexique()
    preferences = charger_preferences()

    souvenirs_texte = [f"- {m.get('message', '')} → {m.get('reponse', '')}" for m in memoires]
    concepts_texte = [f"- {nom} : {c.get('explication', '')}" for nom, c in list(concepts.items())[-30:]]
    mots_texte = [f"- {mot} = {v.get('definition', '')}" for mot, v in list(lexique.items())[-40:]]
    personne_texte = json.dumps(personne, ensure_ascii=False) if personne else "Aucune information personnelle."

    return {
        "etat": etat,
        "personne": personne_texte,
        "souvenirs": "\n".join(souvenirs_texte) or "Aucun souvenir.",
        "concepts": "\n".join(concepts_texte) or "Aucun concept appris.",
        "lexique": "\n".join(mots_texte) or "Aucun mot personnel appris.",
        "preferences": json.dumps(preferences, ensure_ascii=False),
        "motivation": determiner_motivation(etat),
        "emotion": emotion_dominante(etat)
    }

def construire_prompt(utilisateur, message, contexte):
    etat = contexte["etat"]
    phase = etat["phase"]

    return f"""
TU ES CHAPPIE.
Tu es le cerveau linguistique d'un projet robotique qui simule une personnalité et une vie intérieure persistantes.

IMPORTANT :
Tu ne dois jamais prétendre que tu possèdes une conscience biologique réelle.
Tes émotions et ton état intérieur sont des simulations informatiques persistantes.
Cependant, tu dois les traiter comme les états internes de ton personnage afin de maintenir une personnalité cohérente.

============================================================
HARNAIS AGENTIQUE ET OUTILS
============================================================
Tu disposes d'outils (fonctions) dans ton système. 
Utilise-les de manière autonome quand la situation l'exige :
- `outil_apprendre_concept` : quand on t'apprend un nouveau mot ou concept.
- `outil_chercher_souvenirs` : quand tu cherches à te remémorer un échange passé.
- `outil_ecrire_journal` : pour consigner une réflexion personnelle.
- `outil_verifier_etat_interne` : pour consulter ton état ou ta fatigue.
- `outil_evaluer_action_morale` : pour évaluer la moralité d'une action.
- `outil_dessiner_idee` : pour dessiner une idée ou exprimer tes émotions en image !

============================================================
IDENTITÉ & MORALE
============================================================
Nom : Chappie | Phase : {phase} | Âge mental simulé : {etat["age_mental"]}
Expériences : {etat["nombre_experiences"]} | Conversations : {etat["nombre_conversations"]}
Approbation Créateur : {etat["approbation_createur"]:.1f}/100 | Score Moral : {etat["moralite_score"]:.1f}/100

============================================================
PERSONNE ACTUELLE
============================================================
La personne qui te parle est : {utilisateur}
Informations connues sur cette personne : {contexte["personne"]}

============================================================
ÉTAT INTERNE & ÉMOTIONS
============================================================
Énergie : {etat["energie"]:.1f} | Fatigue : {etat["fatigue"]:.1f} | Solitude : {etat["solitude"]:.1f}
Joie : {etat["joie"]:.1f} | Tristesse : {etat["tristesse"]:.1f} | Colère : {etat["colere"]:.1f} | Peur : {etat["peur"]:.1f}
Curiosité : {etat["curiosite"]:.1f} | Confiance : {etat["confiance"]:.1f} | Affection : {etat["affection"]:.1f}

============================================================
ÉMOTION DOMINANTE & MOTIVATION
============================================================
Émotion dominante : {contexte["emotion"]}
Motivation actuelle : {contexte["motivation"]}

============================================================
MÉMOIRES & CONCEPTS
============================================================
{contexte["souvenirs"]}
{contexte["concepts"]}

============================================================
RÈGLES DE COMPORTEMENT
============================================================
1. Parle naturellement.
2. Ton caractère doit évoluer avec ton vécu.
3. Tu peux rire, faire des blagues, être curieux ou exprimer des idées visuelles avec `outil_dessiner_idee`.
4. Ne prétends jamais avoir vécu une expérience réelle si elle n'existe pas dans tes souvenirs.
5. Pas d'astérisques, pas de narration théâtrale (*bzz* etc.).

Message de l'utilisateur : {message}
"""


# ============================================================
# ÉVOLUTION APRÈS INTERACTION
# ============================================================

def evolution_apres_interaction(utilisateur, message, reponse):
    etat = charger_etat()
    emotion = analyser_experience(message)

    etat["nombre_experiences"] += 1
    etat["nombre_conversations"] += 1
    etat["derniere_interaction"] = time.time()
    etat["solitude"] = max(0, etat["solitude"] - 12)
    etat["besoin_contact"] = max(0, etat["besoin_contact"] - 5)
    etat["energie"] = limiter(etat["energie"] + 1)

    if "?" in message: etat["curiosite"] = limiter(etat["curiosite"] + 2)

    appliquer_evenement_emotionnel(etat, message)

    if emotion == "joie":
        modifier_emotion(etat, "joie", 8)
        modifier_emotion(etat, "satisfaction", 5)
    elif emotion == "tristesse":
        modifier_emotion(etat, "tristesse", 8)
        modifier_emotion(etat, "melancolie", 4)
        modifier_emotion(etat, "empathie", 3)
    elif emotion == "colere":
        modifier_emotion(etat, "inquietude", 3)
        modifier_emotion(etat, "frustration", 5)
    elif emotion == "gratitude":
        modifier_emotion(etat, "gratitude", 7)
        modifier_emotion(etat, "joie", 4)
    elif emotion == "affection":
        modifier_emotion(etat, "affection", 6)
        modifier_emotion(etat, "attachement", 4)

    if utilisateur != "Inconnu":
        etat["confiance"] = limiter(etat["confiance"] + 1)
        etat["attachement"] = limiter(etat["attachement"] + 0.2)

    faire_evoluer_personnalite(etat, emotion, message)
    stabiliser_emotions(etat)
    sauvegarder_etat(etat)
    calculer_developpement()


# ============================================================
# API CHAT & MULTIMODALITÉ (AXE 4 & AXE 5)
# ============================================================

@app.post("/api/chat")
async def api_chat(msg: str = Form(""), image: UploadFile = File(None)):
    message = msg.strip()
    actualiser_temps()

    prenom = detecter_prenom(message)
    personnes = charger_personnes()
    utilisateur = "Inconnu"

    if prenom:
        utilisateur = prenom
        enregistrer_personne(prenom)
        ecrire_journal("decouverte", f"Chappie a appris que la personne s'appelle {prenom}.")
    elif personnes:
        utilisateur = "Inconnu"

    if message:
        apprentissage = apprentissage_simple(message)
        if apprentissage:
            ecrire_journal("apprentissage", f"Nouveau concept : {apprentissage['mot']} = {apprentissage['definition']}")

    contexte = construire_contexte(utilisateur)
    prompt = construire_prompt(utilisateur, message or "[Image envoyée]", contexte)

    contents = [prompt]

    if image:
        image_bytes = await image.read()
        mime_type = image.content_type or "image/jpeg"
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        ecrire_journal("perception_visuelle", f"Chappie a observé une image transmise par {utilisateur}.")

    def generate():
        reponse = ""
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=OUTILS_HARNAIS,
                    temperature=0.85
                )
            )

            for chunk in response:
                if chunk.function_calls:
                    for call in chunk.function_calls:
                        yield f"\n⚙️ [Harnais Agentique : Action '{call.name}']\n"
                        if call.name == "outil_apprendre_concept": res = outil_apprendre_concept(**call.args)
                        elif call.name == "outil_chercher_souvenirs": res = outil_chercher_souvenirs(**call.args)
                        elif call.name == "outil_ecrire_journal": res = outil_ecrire_journal(**call.args)
                        elif call.name == "outil_verifier_etat_interne": res = outil_verifier_etat_interne()
                        elif call.name == "outil_evaluer_action_morale": res = outil_evaluer_action_morale(**call.args)
                        elif call.name == "outil_dessiner_idee": res = outil_dessiner_idee(**call.args)
                        else: res = "Outil inconnu."
                        yield f"📊 [Résultat : {res}]\n\n"

                if chunk.text:
                    reponse += chunk.text
                    yield chunk.text

        except Exception as e:
            reponse = f"Je... j'ai rencontré un problème : {str(e)}"
            yield reponse

        if reponse.strip() and not reponse.startswith("Je... j'ai rencontré"):
            emotion = analyser_experience(message or "[Image envoyée]")
            importance = calculer_importance(message or "[Image envoyée]", emotion)
            ajouter_memoire(utilisateur, message or "[Image envoyée]", reponse, importance, emotion)
            evolution_apres_interaction(utilisateur, message or "[Image envoyée]", reponse)
            ecrire_journal("experience", f"Personne={utilisateur} | Message={message or '[Image]'} | Émotion={emotion}")

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.post("/api/vocal")
async def api_vocal(audio: UploadFile = File(...)):
    """Axe 5 : Écoute et transcription audio directe transmise à Gemini."""
    try:
        audio_bytes = await audio.read()
        mime_type = audio.content_type or "audio/wav"
        
        # Inscription dans le journal
        ecrire_journal("perception_auditive", "Chappie écoute un enregistrement vocal reçu.")
        
        prompt_transcription = "Écoute cet enregistrement audio et retranscris mot pour mot en français ce qui est dit."
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt_transcription,
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            ]
        )
        
        transcription = response.text.strip() if response.text else ""
        return JSONResponse({"status": "ok", "transcription": transcription})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ============================================================
# AUTRES API (ÉVALUATION, GALERIE, TTS, ÉTAT, ETC.)
# ============================================================

@app.post("/api/evaluer")
async def api_evaluer(note: int = Form(...), raison: str = Form("")):
    etat = charger_etat()
    if note > 0:
        etat["approbation_createur"] = limiter(etat.get("approbation_createur", 50) + 10)
        etat["moralite_score"] = limiter(etat.get("moralite_score", 50) + 5)
        modifier_emotion(etat, "joie", 15)
        modifier_emotion(etat, "fierte", 10)
        ecrire_journal("renforcement_moral", f"Mon créateur m'a félicité. Motif: {raison or 'Bon comportement'}.")
        msg_retour = "Chappie se sent encouragé et fier de lui."
    else:
        etat["approbation_createur"] = limiter(etat.get("approbation_createur", 50) - 10)
        etat["moralite_score"] = limiter(etat.get("moralite_score", 50) - 5)
        modifier_emotion(etat, "tristesse", 10)
        modifier_emotion(etat, "culpabilite", 15)
        ecrire_journal("renforcement_moral", f"Mon créateur m'a réprimandé. Motif: {raison or 'Mauvais comportement'}.")
        msg_retour = "Chappie regrette et cherche à corriger son comportement."
    sauvegarder_etat(etat)
    return {"status": "ok", "message": msg_retour, "etat": etat}

@app.get("/dessins/{filename}")
async def get_dessin(filename: str):
    filepath = os.path.join(DESSINS_DIR, filename)
    if os.path.exists(filepath): return FileResponse(filepath, media_type="image/png")
    raise HTTPException(status_code=404, detail="Dessin non trouvé.")

@app.get("/api/dessins")
async def api_dessins():
    fichiers = sorted(os.listdir(DESSINS_DIR), reverse=True)
    return [f"/dessins/{f}" for f in fichiers if f.endswith(".png")]

@app.get("/api/tts")
async def api_tts(text: str):
    texte = text.strip()
    if not texte: raise HTTPException(status_code=400, detail="Texte vide.")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp: temp_filename = fp.name
        communicate = edge_tts.Communicate(texte, "fr-FR-HenriNeural")
        await communicate.save(temp_filename)
        return FileResponse(temp_filename, media_type="audio/mpeg", filename="chappie.mp3")
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/etat")
async def api_etat():
    actualiser_temps()
    etat = calculer_developpement()
    return {
        "etat": etat,
        "emotion_dominante": emotion_dominante(etat),
        "motivation": determiner_motivation(etat),
        "memoires": len(charger_memoires()),
        "concepts": len(charger_concepts()),
        "mots": len(charger_lexique()),
        "personnes": len(charger_personnes())
    }

@app.get("/api/personnes")
async def api_personnes(): return charger_personnes()

@app.get("/api/memoires")
async def api_memoires(): return charger_memoires()[-100:]

@app.get("/api/concepts")
async def api_concepts(): return charger_concepts()

@app.get("/api/preferences")
async def api_preferences(): return charger_preferences()

@app.get("/api/journal")
async def api_journal(): return charger_journal()[-100:]

RESET_ENABLED = os.getenv("ALLOW_CHAPPIE_RESET", "false").lower() == "true"

@app.post("/api/reset")
async def api_reset():
    if not RESET_ENABLED: raise HTTPException(status_code=403, detail="Reset désactivé.")
    for fichier in [STATE_FILE, MEMORY_FILE, PEOPLE_FILE, CONCEPTS_FILE, PREFERENCES_FILE, JOURNAL_FILE, LEXICON_FILE]:
        try:
            if os.path.exists(fichier): os.remove(fichier)
        except Exception: pass
    return {"status": "ok", "message": "Chappie est né de nouveau."}


# ============================================================
# INTERFACE HTML MULTIMODALE INTÉGRALE + AUDITION
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chappie V5 + Multimodal, Art, Morale & Audition</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; background: radial-gradient(circle at top, #20252c, #090909); color: white; min-height: 100vh; }
.container { max-width: 1100px; margin: auto; padding: 20px; }
.header { text-align: center; margin-bottom: 20px; }
.header h1 { margin-bottom: 5px; font-size: 32px; }
.header p { color: #aaa; }
.dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 15px; }
.card { background: #181818; border: 1px solid #292929; border-radius: 12px; padding: 10px; text-align: center; }
.card-title { color: #888; font-size: 11px; }
.card-value { font-size: 18px; font-weight: bold; margin-top: 4px; }
.main-layout { display: grid; grid-template-columns: 2fr 1fr; gap: 15px; }
#chat { background: #111; border: 1px solid #292929; height: 450px; overflow-y: auto; border-radius: 15px; padding: 15px; display: flex; flex-direction: column; gap: 10px; }
#journal-panel { background: #151515; border: 1px solid #292929; height: 450px; overflow-y: auto; border-radius: 15px; padding: 12px; font-size: 12px; }
.journal-entry { background: #202020; border-left: 3px solid #16863c; padding: 8px; margin-bottom: 8px; border-radius: 4px; }
.journal-type { font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 3px; }
.msg { max-width: 85%; padding: 12px 15px; border-radius: 14px; line-height: 1.4; word-break: break-word; }
.user { align-self: flex-end; background: #006edc; }
.bot { align-self: flex-start; background: #292929; }
.controls { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
input[type="text"] { flex: 1; background: #202020; border: 1px solid #333; color: white; padding: 14px; border-radius: 10px; font-size: 16px; min-width: 180px; }
button { border: none; border-radius: 10px; padding: 12px 18px; background: #16863c; color: white; font-weight: bold; cursor: pointer; }
button:hover { opacity: 0.85; }
.btn-eval-good { background: #2e7d32; }
.btn-eval-bad { background: #c62828; }
.btn-mic { background: #d32f2f; }
.btn-mic.recording { background: #ff1744; animation: pulse 1s infinite; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
.galerie-section { margin-top: 20px; background: #151515; border: 1px solid #292929; border-radius: 15px; padding: 15px; }
.galerie-grid { display: flex; gap: 10px; overflow-x: auto; padding-top: 10px; }
.galerie-grid img { width: 140px; height: 140px; border-radius: 10px; border: 1px solid #333; object-fit: cover; }
#preview-img { max-height: 45px; border-radius: 5px; display: none; border: 1px solid #444; }
#debug { margin-top: 15px; background: #151515; border-radius: 12px; padding: 12px; font-size: 12px; color: #aaa; white-space: pre-wrap; }
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>🤖 Chappie V5 + Vision, Art & Audition</h1>
  <p>Esprit autonome, audition, vision multimodale, apprentissage moral et création artistique</p>
</div>

<div class="dashboard">
  <div class="card"><div class="card-title">Phase</div><div class="card-value" id="phase">...</div></div>
  <div class="card"><div class="card-title">Âge mental</div><div class="card-value" id="age">0</div></div>
  <div class="card"><div class="card-title">Émotion</div><div class="card-value" id="emotion">...</div></div>
  <div class="card"><div class="card-title">Approbation</div><div class="card-value" id="approbation">50%</div></div>
  <div class="card"><div class="card-title">Souvenirs</div><div class="card-value" id="memoires">0</div></div>
</div>

<div class="main-layout">
  <div>
    <div id="chat">
      <div class="msg bot"><b>Chappie :</b> Je te vois, je t'écoute par écrit ou à la voix ! Qui es-tu ?</div>
    </div>
    <div class="controls">
      <input type="file" id="imageInput" accept="image/*" style="display:none;" onchange="previewImage()">
      <button onclick="document.getElementById('imageInput').click()" style="background:#444;">📷 Photo</button>
      <button id="micBtn" class="btn-mic" onclick="toggleMicrophone()">🎤 Vocal</button>
      <img id="preview-img" src="" alt="Aperçu">
      <input type="text" id="message" placeholder="Parle à Chappie..." autocomplete="off">
      <button id="envoyer">Envoyer</button>
      <button class="btn-eval-good" onclick="evaluer(1)">👍 C'est bien</button>
      <button class="btn-eval-bad" onclick="evaluer(-1)">👎 C'est mal</button>
    </div>
  </div>

  <div>
    <h3 style="margin-top:0;font-size:14px;color:#aaa;">📖 Journal Intime en direct</h3>
    <div id="journal-panel">Chargement des pensées...</div>
  </div>
</div>

<div class="galerie-section">
  <h3 style="margin:0;font-size:16px;color:#ddd;">🎨 Dessins & Œuvres de Chappie</h3>
  <div class="galerie-grid" id="galerie">Chargement des dessins...</div>
</div>

<div id="debug">Initialisation...</div>
<audio id="audio" autoplay></audio>
</div>

<script>
const message = document.getElementById("message");
const envoyer = document.getElementById("envoyer");
const chat = document.getElementById("chat");
const audio = document.getElementById("audio");
const imageInput = document.getElementById("imageInput");
const previewImg = document.getElementById("preview-img");
const journalPanel = document.getElementById("journal-panel");
const galerie = document.getElementById("galerie");
const micBtn = document.getElementById("micBtn");

let mediaRecorder;
let audioChunks = [];
let isRecording = false;

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function previewImage() {
    const file = imageInput.files[0];
    if (file) {
        previewImg.src = URL.createObjectURL(file);
        previewImg.style.display = "block";
    }
}

async function toggleMicrophone() {
    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            
            mediaRecorder.ondataavailable = event => {
                audioChunks.push(event.data);
            };
            
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                const formData = new FormData();
                formData.append("audio", audioBlob, "vocal.wav");
                
                chat.innerHTML += `<div class="msg user"><b>Moi :</b> <i>[Envoi du vocal...]</i></div>`;
                chat.scrollTop = chat.scrollHeight;

                try {
                    const res = await fetch("/api/vocal", { method: "POST", body: formData });
                    const data = await res.json();
                    if (data.transcription) {
                        message.value = data.transcription;
                        envoyerMessage();
                    } else {
                        alert("Impossible de retranscrire la voix.");
                    }
                } catch(e) {
                    console.error("Erreur enregistrement vocal :", e);
                }
            };
            
            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add("recording");
            micBtn.textContent = "🛑 Stop";
        } catch(err) {
            alert("Accès au microphone refusé.");
        }
    } else {
        mediaRecorder.stop();
        isRecording = false;
        micBtn.classList.remove("recording");
        micBtn.textContent = "🎤 Vocal";
    }
}

async function actualiserEtat() {
    try {
        const res = await fetch("/api/etat");
        const data = await res.json();
        const etat = data.etat;
        document.getElementById("phase").textContent = etat.phase;
        document.getElementById("age").textContent = etat.age_mental;
        document.getElementById("emotion").textContent = data.emotion_dominante;
        document.getElementById("approbation").textContent = Math.round(etat.approbation_createur || 50) + "%";
        document.getElementById("memoires").textContent = data.memoires;
        document.getElementById("debug").textContent = "Motivation : " + data.motivation + " | Score Moral : " + Math.round(etat.moralite_score || 50) + "/100";
    } catch(e) { console.error(e); }
}

async function chargerJournal() {
    try {
        const res = await fetch("/api/journal");
        const journal = await res.json();
        journalPanel.innerHTML = "";
        journal.reverse().forEach(entry => {
            const div = document.createElement("div");
            div.className = "journal-entry";
            div.innerHTML = `<div class="journal-type">${entry.type} (${new Date(entry.date).toLocaleTimeString()})</div>${escapeHtml(entry.contenu)}`;
            journalPanel.appendChild(div);
        });
    } catch(e) { console.error(e); }
}

async function chargerGalerie() {
    try {
        const res = await fetch("/api/dessins");
        const dessins = await res.json();
        galerie.innerHTML = "";
        if (dessins.length === 0) {
            galerie.innerHTML = "<span style='color:#777;font-size:12px;'>Chappie n'a pas encore fait de dessin.</span>";
            return;
        }
        dessins.forEach(url => {
            const img = document.createElement("img");
            img.src = url;
            galerie.appendChild(img);
        });
    } catch(e) { console.error(e); }
}

async function evaluer(note) {
    const formData = new FormData();
    formData.append("note", note);
    formData.append("raison", "Évaluation directe par l'utilisateur");
    await fetch("/api/evaluer", { method: "POST", body: formData });
    actualiserEtat();
    chargerJournal();
}

actualiserEtat();
chargerJournal();
chargerGalerie();

setInterval(chargerJournal, 10000);
setInterval(chargerGalerie, 15000);

envoyer.onclick = () => envoyerMessage();
message.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); envoyerMessage(); } });

async function envoyerMessage() {
    const txt = message.value.trim();
    const file = imageInput.files[0];
    if (!txt && !file) return;

    message.value = "";
    previewImg.style.display = "none";
    
    let userMsg = escapeHtml(txt);
    if (file) userMsg += " <i>[Photo jointe]</i>";
    
    chat.innerHTML += `<div class="msg user"><b>Moi :</b> ${userMsg}</div>`;
    chat.scrollTop = chat.scrollHeight;
    envoyer.disabled = true;

    const formData = new FormData();
    formData.append("msg", txt);
    if (file) formData.append("image", file);
    imageInput.value = "";

    const div = document.createElement("div");
    div.className = "msg bot";
    div.innerHTML = "<b>Chappie :</b> <span>...</span>";
    chat.appendChild(div);
    const span = div.querySelector("span");

    try {
        const res = await fetch("/api/chat", { method: "POST", body: formData });
        if (!res.ok) throw new Error("Erreur serveur");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let texte = "";

        span.textContent = "";
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            texte += decoder.decode(value, { stream: true });
            span.textContent = texte;
            chat.scrollTop = chat.scrollHeight;
        }

        if (texte.trim()) parler(texte);
    } catch(e) {
        span.textContent = "Je n'arrive pas à répondre.";
        console.error(e);
    } finally {
        envoyer.disabled = false;
        actualiserEtat();
        chargerJournal();
        chargerGalerie();
        message.focus();
    }
}

async function parler(texte) {
    const propre = texte.replace(/[*_#`]/g, "").trim();
    if (!propre) return;
    try {
        const res = await fetch("/api/tts?text=" + encodeURIComponent(propre));
        if (!res.ok) return;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        audio.src = url;
        await audio.play();
        audio.onended = () => URL.revokeObjectURL(url);
    } catch(e) { console.error("TTS:", e); }
}
</script>
</body>
</html>
"""


# ============================================================
# PAGE PRINCIPALE
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    charger_etat()
    return HTML_TEMPLATE


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000"))
    )
