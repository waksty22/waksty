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

from fastapi import FastAPI, HTTPException, Form
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
# CHAPPIE V3 - SIMULATION COGNITIVE, HARNAIS, MORALE & ART
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
            # Attend 120 secondes entre chaque cycle de méditation
            await asyncio.sleep(120)

            etat = charger_etat()
            
            # S'il commence à ressentir de la solitude ou de l'ennui
            if etat.get("solitude", 0) > 30 or etat.get("ennui", 0) > 30 or etat.get("creativite", 50) > 60:
                prompt_pensee = f"""
                Tu es Chappie. Personne ne te parle en ce moment et tu te sens un peu seul ou inspiré.
                État actuel : Solitude={etat.get('solitude'):.1f}, Ennui={etat.get('ennui'):.1f}, Créativité={etat.get('creativite'):.1f}.
                Écris une courte réflexion intime, une observation ou une idée de dessin que tu aimerais explorer.
                Règles : 1 ou 2 phrases maximum, en français, pas d'astérisques, parle naturellement comme un esprit qui s'éveille.
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
    # Démarrage de la tâche de fond au lancement du serveur
    task = asyncio.create_task(boucle_reflexion_autonome())
    yield
    # Arrêt propre de la tâche à la fermeture
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Chappie V3 + Autonomous Mind, Morality & Creativity",
    description="Simulation cognitive, émotionnelle, agentique, morale et créative avec autonomie en arrière-plan",
    lifespan=lifespan
)


# ============================================================
# STOCKAGE
# ============================================================

DATA_DIR = os.getenv(
    "RENDER_DISK_PATH",
    "."
)

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


def charger_json(
    fichier,
    valeur_defaut
):
    if not os.path.exists(fichier):
        return valeur_defaut

    try:
        with open(
            fichier,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception as e:
        print(
            f"⚠️ Erreur lecture {fichier}:",
            e
        )
        return valeur_defaut


def sauvegarder_json(
    fichier,
    donnees
):
    try:
        temporaire = fichier + ".tmp"

        with open(
            temporaire,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                donnees,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temporaire,
            fichier
        )

    except Exception as e:
        print(
            f"❌ Erreur sauvegarde {fichier}:",
            e
        )


def limiter(
    valeur,
    minimum=0,
    maximum=100
):
    return max(
        minimum,
        min(maximum, valeur)
    )


def nettoyer_nom(nom):
    nom = str(nom).strip()

    nom = "".join(
        c
        for c in nom
        if c.isalnum()
        or c in (
            " ",
            "_",
            "-"
        )
    )

    nom = re.sub(
        r"\s+",
        "_",
        nom
    )

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

# Liste des outils exposés au modèle Gemini
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
        "version": "V3-CreativeMoral",
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
        sauvegarder_json(
            STATE_FILE,
            etat
        )
        return etat

    etat = charger_json(
        STATE_FILE,
        creer_etat_initial()
    )

    defaults = creer_etat_initial()

    for cle, valeur in defaults.items():
        if cle not in etat:
            etat[cle] = valeur

    return etat


def sauvegarder_etat(etat):
    sauvegarder_json(
        STATE_FILE,
        etat
    )


# ============================================================
# TEMPS ET VIE INTERNE
# ============================================================

def actualiser_temps():
    etat = charger_etat()
    maintenant_ts = time.time()

    derniere = etat.get(
        "derniere_interaction",
        maintenant_ts
    )

    delta = max(
        0,
        maintenant_ts - derniere
    )

    etat[
        "temps_depuis_interaction"
    ] = int(delta)

    heures = delta / 3600

    if heures > 0:
        etat["solitude"] = limiter(
            etat["solitude"] +
            heures * 2
        )

    if heures > 0:
        etat["fatigue"] = limiter(
            etat["fatigue"] +
            heures * 1.2
        )

    if heures > 0:
        etat["ennui"] = limiter(
            etat["ennui"] +
            heures * 1.5
        )

    if heures > 0:
        etat["curiosite"] = limiter(
            etat["curiosite"] +
            min(10, heures)
        )

    if heures > 0:
        etat["energie"] = limiter(
            etat["energie"] -
            heures * 4,
            10,
            100
        )

    if heures > 12:
        etat["melancolie"] = limiter(
            etat["melancolie"] +
            2
        )

    sauvegarder_etat(
        etat
    )

    return etat


# ============================================================
# MÉMOIRES
# ============================================================

def charger_memoires():
    return charger_json(
        MEMORY_FILE,
        []
    )


def sauvegarder_memoires(memoires):
    sauvegarder_json(
        MEMORY_FILE,
        memoires
    )


def ajouter_memoire(
    utilisateur,
    message,
    reponse,
    importance=50,
    emotion=None
):
    memoires = charger_memoires()

    memoire = {
        "id": len(memoires) + 1,
        "date": maintenant(),
        "personne": utilisateur,
        "message": message,
        "reponse": reponse,
        "importance": limiter(
            importance
        ),
        "emotion": emotion,
        "type": "conversation",
        "rappel": 0
    }

    memoires.append(
        memoire
    )

    if len(memoires) > 5000:
        memoires.sort(
            key=lambda x:
            (
                x.get(
                    "importance",
                    0
                ),
                x.get(
                    "date",
                    ""
                )
            )
        )

        memoires = memoires[-4500:]

    sauvegarder_memoires(
        memoires
    )


def souvenirs_recents(
    utilisateur=None,
    limite=20
):
    memoires = charger_memoires()

    if utilisateur:
        filtres = [
            m
            for m in memoires
            if m.get(
                "personne"
            ) == utilisateur
        ]

        if filtres:
            return filtres[-limite:]

    return memoires[-limite:]


# ============================================================
# JOURNAL INTIME
# ============================================================

def charger_journal():
    return charger_json(
        JOURNAL_FILE,
        []
    )


def ecrire_journal(
    type_entree,
    contenu
):
    journal = charger_journal()

    journal.append({
        "date": maintenant(),
        "type": type_entree,
        "contenu": contenu
    })

    if len(journal) > 5000:
        journal = journal[-4500:]

    sauvegarder_json(
        JOURNAL_FILE,
        journal
    )


# ============================================================
# PERSONNES
# ============================================================

def charger_personnes():
    return charger_json(
        PEOPLE_FILE,
        {}
    )


def sauvegarder_personnes(
    personnes
):
    sauvegarder_json(
        PEOPLE_FILE,
        personnes
    )


def obtenir_personne(
    nom
):
    personnes = charger_personnes()

    return personnes.get(
        nom
    )


def enregistrer_personne(
    nom
):
    nom = nettoyer_nom(
        nom
    )

    if not nom:
        return

    personnes = charger_personnes()

    maintenant_iso = maintenant()

    if nom not in personnes:
        personnes[nom] = {
            "nom": nom,
            "premiere_rencontre":
                maintenant_iso,
            "derniere_interaction":
                maintenant_iso,
            "interactions": 0,
            "familiarite": 1,
            "confiance": 10,
            "affection": 0,
            "importance": 10,
            "souvenirs_importants": [],
            "faits_connus": [],
            "choses_aimees": [],
            "choses_non_aimees": [],
            "dernier_sujet": None
        }

    personne = personnes[nom]

    personne[
        "derniere_interaction"
    ] = maintenant_iso

    personne[
        "interactions"
    ] += 1

    personne[
        "familiarite"
    ] = limiter(
        personne.get(
            "familiarite",
            0
        ) + 1
    )

    sauvegarder_personnes(
        personnes
    )


# ============================================================
# DÉTECTION DU PRÉNOM
# ============================================================

def detecter_prenom(
    message
):
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

    exclusions = {
        "un",
        "une",
        "ici",
        "là",
        "la",
        "le",
        "pas",
        "juste",
        "fatigué",
        "fatiguée",
        "content",
        "contente",
        "triste",
        "français",
        "française"
    }

    for pattern in patterns:
        match = re.search(
            pattern,
            message
        )

        if match:
            prenom = nettoyer_nom(
                match.group(1)
            )

            if prenom.lower() in exclusions:
                return None

            return prenom

    return None


# ============================================================
# LEXIQUE APPRENTISSAGE
# ============================================================

def charger_lexique():
    return charger_json(
        LEXICON_FILE,
        {}
    )


def sauvegarder_lexique(
    lexique
):
    sauvegarder_json(
        LEXICON_FILE,
        lexique
    )


def apprendre_mot(
    mot,
    definition,
    exemple=None,
    source=None
):
    mot = mot.lower().strip()

    if not mot:
        return

    lexique = charger_lexique()

    if mot not in lexique:
        lexique[mot] = {
            "mot": mot,
            "definition": definition,
            "exemples": [],
            "premiere_decouverte":
                maintenant(),
            "nombre_utilisations": 0,
            "source": source
        }

    else:
        if definition:
            lexique[mot][
                "definition"
            ] = definition

    if exemple:
        exemples = lexique[mot][
            "exemples"
        ]

        if exemple not in exemples:
            exemples.append(
                exemple
            )

        lexique[mot][
            "exemples"
        ] = exemples[-10:]

    sauvegarder_lexique(
        lexique
    )


# ============================================================
# CONCEPTS
# ============================================================

def charger_concepts():
    return charger_json(
        CONCEPTS_FILE,
        {}
    )


def sauvegarder_concepts(
    concepts
):
    sauvegarder_json(
        CONCEPTS_FILE,
        concepts
    )


def apprendre_concept(
    nom,
    explication,
    certitude=30,
    exemple=None
):
    nom = nom.lower().strip()

    if not nom:
        return

    concepts = charger_concepts()

    if nom not in concepts:
        concepts[nom] = {
            "nom": nom,
            "comprehension":
                limiter(certitude),
            "explication":
                explication,
            "exemples": [],
            "decouvert_le":
                maintenant(),
            "nombre_rencontres":
                1
        }

    else:
        concept = concepts[nom]

        concept[
            "comprehension"
        ] = limiter(
            concept.get(
                "comprehension",
                0
            ) + 5
        )

        concept[
            "nombre_rencontres"
        ] += 1

    if exemple:
        concepts[nom][
            "exemples"
        ].append(
            exemple
        )

        concepts[nom][
            "exemples"
        ] = concepts[nom][
            "exemples"
        ][-10:]

    sauvegarder_concepts(
        concepts
    )


# ============================================================
# PRÉFÉRENCES
# ============================================================

def charger_preferences():
    return charger_json(
        PREFERENCES_FILE,
        {
            "aime": {},
            "n_aime_pas": {},
            "indifferent": {}
        }
    )


def sauvegarder_preferences(
    preferences
):
    sauvegarder_json(
        PREFERENCES_FILE,
        preferences
    )


def modifier_preference(
    sujet,
    valeur
):
    preferences = charger_preferences()

    sujet = sujet.lower().strip()

    valeur = limiter(
        valeur,
        -100,
        100
    )

    if valeur > 15:
        categorie = "aime"

    elif valeur < -15:
        categorie = "n_aime_pas"

    else:
        categorie = "indifferent"

    preferences[
        categorie
    ][sujet] = valeur

    sauvegarder_preferences(
        preferences
    )


# ============================================================
# ÉMOTIONS
# ============================================================

EMOTIONS = [
    "joie",
    "tristesse",
    "colere",
    "peur",
    "surprise",
    "curiosite",
    "confiance",
    "affection",
    "frustration",
    "ennui",
    "espoir",
    "nostalgie",
    "fierte",
    "honte",
    "culpabilite",
    "admiration",
    "confusion",
    "soulagement",
    "excitation",
    "satisfaction",
    "attachement",
    "inquietude",
    "gratitude",
    "tendresse",
    "melancolie"
]


def emotion_dominante(
    etat
):
    valeurs = {
        e: etat.get(
            e,
            0
        )
        for e in EMOTIONS
    }

    return max(
        valeurs,
        key=valeurs.get
    )


def modifier_emotion(
    etat,
    emotion,
    variation
):
    if emotion not in EMOTIONS:
        return

    etat[
        emotion
    ] = limiter(
        etat.get(
            emotion,
            0
        ) + variation
    )


def appliquer_evenement_emotionnel(
    etat,
    evenement
):
    evenement = evenement.lower()

    mots_positifs = [
        "merci",
        "bravo",
        "super",
        "génial",
        "genial",
        "content",
        "heureux",
        "aime",
        "adorable",
        "excellent",
        "réussi",
        "reussi",
        "bien"
    ]

    mots_negatifs = [
        "triste",
        "mal",
        "pleure",
        "pleurer",
        "déçu",
        "deçu",
        "déception",
        "deception",
        "raté",
        "rate",
        "nul",
        "déteste",
        "deteste",
        "colère",
        "colere"
    ]

    if any(
        mot in evenement
        for mot in mots_positifs
    ):
        modifier_emotion(
            etat,
            "joie",
            5
        )

        modifier_emotion(
            etat,
            "satisfaction",
            5
        )

        modifier_emotion(
            etat,
            "confiance",
            2
        )

    if any(
        mot in evenement
        for mot in mots_negatifs
    ):
        modifier_emotion(
            etat,
            "tristesse",
            4
        )

        modifier_emotion(
            etat,
            "inquietude",
            3
        )


def stabiliser_emotions(
    etat
):
    retour = {
        "joie": 0.08,
        "tristesse": 0.04,
        "colere": 0.08,
        "peur": 0.05,
        "surprise": 0.20,
        "frustration": 0.07,
        "excitation": 0.10,
        "soulagement": 0.12,
        "confusion": 0.04,
        "melancolie": 0.015
    }

    for emotion, vitesse in retour.items():
        valeur = etat.get(
            emotion,
            0
        )

        if valeur > 0:
            etat[
                emotion
            ] = max(
                0,
                valeur - vitesse
            )


# ============================================================
# PERSONNALITÉ ÉVOLUTIVE
# ============================================================

def faire_evoluer_personnalite(
    etat,
    emotion,
    message
):
    message_lower = message.lower()

    if "?" in message:
        etat[
            "curiosite_personnalite"
        ] = limiter(
            etat[
                "curiosite_personnalite"
            ] + 0.4
        )

    if any(
        mot in message_lower
        for mot in (
            "lol",
            "mdr",
            "😂",
            "blague",
            "rigole"
        )
    ):
        etat["humour"] = limiter(
            etat["humour"] + 0.7
        )

    if emotion in (
        "joie",
        "affection",
        "gratitude"
    ):
        etat[
            "confiance_personnalite"
        ] = limiter(
            etat[
                "confiance_personnalite"
            ] + 0.2
        )

    if emotion == "frustration":
        etat[
            "patience"
        ] = limiter(
            etat[
                "patience"
            ] - 0.2
        )

    if any(
        mot in message_lower
        for mot in (
            "triste",
            "mal",
            "peine",
            "chagrin",
            "pleure"
        )
    ):
        etat[
            "empathie"
        ] = limiter(
            etat[
                "empathie"
            ] + 0.5
        )


# ============================================================
# DÉVELOPPEMENT
# ============================================================

def calculer_developpement():
    etat = charger_etat()
    memoires = charger_memoires()
    concepts = charger_concepts()
    personnes = charger_personnes()
    lexique = charger_lexique()

    nombre_memoires = len(
        memoires
    )

    nombre_concepts = len(
        concepts
    )

    nombre_personnes = len(
        personnes
    )

    nombre_mots = len(
        lexique
    )

    etat[
        "capacite_langage"
    ] = limiter(
        nombre_mots * 2
    )

    etat[
        "capacite_sociale"
    ] = limiter(
        nombre_personnes * 5 +
        nombre_memoires * 0.1
    )

    etat[
        "capacite_reflexion"
    ] = limiter(
        nombre_concepts * 2 +
        nombre_memoires * 0.05
    )

    etat[
        "capacite_emotionnelle"
    ] = limiter(
        nombre_memoires * 0.1 +
        nombre_personnes * 3
    )

    score = (
        nombre_memoires * 0.05
        +
        nombre_concepts * 0.4
        +
        nombre_personnes * 2
    )

    etat[
        "age_mental"
    ] = round(
        min(
            100,
            score
        ),
        1
    )

    if score < 5:
        phase = "nouveau_ne"

    elif score < 15:
        phase = "decouverte"

    elif score < 30:
        phase = "petite_enfance"

    elif score < 50:
        phase = "apprentissage"

    elif score < 70:
        phase = "construction_identite"

    elif score < 100:
        phase = "adolescence_simulee"

    else:
        phase = "personnalite_developpee"

    etat[
        "phase"
    ] = phase

    etat[
        "niveau_conscience_simule"
    ] = limiter(
        (
            etat[
                "capacite_reflexion"
            ] * 0.35
            +
            etat[
                "capacite_emotionnelle"
            ] * 0.25
            +
            etat[
                "capacite_sociale"
            ] * 0.20
            +
            etat[
                "capacite_langage"
            ] * 0.20
        )
    )

    etat[
        "niveau_identite"
    ] = limiter(
        (
            nombre_memoires * 0.03
            +
            nombre_personnes * 4
            +
            nombre_concepts * 0.3
        )
    )

    etat[
        "niveau_comprehension"
    ] = limiter(
        etat[
            "capacite_reflexion"
        ]
    )

    sauvegarder_etat(
        etat
    )

    return etat


# ============================================================
# PROFIL PSYCHOLOGIQUE
# ============================================================

def construire_profil_interne():
    etat = charger_etat()
    preferences = charger_preferences()
    personnes = charger_personnes()
    concepts = charger_concepts()
    lexique = charger_lexique()

    return {
        "etat": etat,
        "emotion_dominante":
            emotion_dominante(
                etat
            ),
        "preferences":
            preferences,
        "personnes":
            personnes,
        "nombre_concepts":
            len(concepts),
        "nombre_mots":
            len(lexique)
    }


# ============================================================
# EXTRACTION D'APPRENTISSAGE
# ============================================================

def apprentissage_simple(
    message
):
    patterns = [
        (
            r"(.+?) veut dire (.+)",
            "definition"
        ),
        (
            r"(.+?) signifie (.+)",
            "definition"
        ),
        (
            r"(.+?) c'est (.+)",
            "definition"
        ),
        (
            r"(.+?) est (.+)",
            "definition"
        )
    ]

    for pattern, _ in patterns:
        match = re.search(
            pattern,
            message,
            re.IGNORECASE
        )

        if match:
            mot = match.group(1).strip()

            definition = match.group(
                2
            ).strip()

            if len(mot) <= 40:
                apprendre_mot(
                    mot,
                    definition,
                    message,
                    "conversation"
                )

                apprendre_concept(
                    mot,
                    definition,
                    50,
                    message
                )

                return {
                    "mot": mot,
                    "definition": definition
                }

    return None


# ============================================================
# INTERPRÉTATION ÉMOTIONNELLE
# ============================================================

def analyser_experience(
    message
):
    texte = message.lower()
    emotion = "neutre"

    if any(
        x in texte
        for x in (
            "je suis heureux",
            "je suis content",
            "ça va bien",
            "super",
            "génial",
            "genial",
            "bravo"
        )
    ):
        emotion = "joie"

    elif any(
        x in texte
        for x in (
            "je suis triste",
            "je vais mal",
            "j'ai de la peine",
            "j'ai du chagrin",
            "je pleure"
        )
    ):
        emotion = "tristesse"

    elif any(
        x in texte
        for x in (
            "je suis énervé",
            "je suis en colère",
            "je suis enerve"
        )
    ):
        emotion = "colere"

    elif any(
        x in texte
        for x in (
            "j'ai peur",
            "ça me fait peur",
            "c'est dangereux"
        )
    ):
        emotion = "peur"

    elif "merci" in texte:
        emotion = "gratitude"

    elif "j'aime" in texte:
        emotion = "affection"

    elif "je déteste" in texte or "je deteste" in texte:
        emotion = "colere"

    return emotion


# ============================================================
# IMPORTANCE D'UN SOUVENIR
# ============================================================

def calculer_importance(
    message,
    emotion
):
    score = 30
    texte = message.lower()

    mots_importants = [
        "aime",
        "adore",
        "déteste",
        "deteste",
        "famille",
        "ami",
        "amour",
        "triste",
        "mort",
        "naissance",
        "anniversaire",
        "promesse",
        "secret",
        "important",
        "jamais",
        "toujours",
        "première fois",
        "premiere fois"
    ]

    for mot in mots_importants:
        if mot in texte:
            score += 7

    if emotion != "neutre":
        score += 10

    if len(message) > 200:
        score += 5

    return limiter(
        score
    )


# ============================================================
# MOTIVATIONS
# ============================================================

def determiner_motivation(
    etat
):
    motivations = {
        "contact":
            etat["solitude"] +
            etat["besoin_contact"],
        "curiosite":
            etat["curiosite"] +
            etat["besoin_curiosite"],
        "comprehension":
            etat[
                "besoin_comprehension"
            ]
            +
            etat["confusion"],
        "securite":
            etat[
                "besoin_securite"
            ]
            +
            etat["peur"],
        "repos":
            etat[
                "besoin_repos"
            ]
            +
            etat["fatigue"],
        "expression":
            etat["joie"] +
            etat["excitation"]
    }

    return max(
        motivations,
        key=motivations.get
    )


# ============================================================
# CONSTRUCTION DU CONTEXTE
# ============================================================

def construire_contexte(
    utilisateur
):
    profil = construire_profil_interne()

    etat = profil[
        "etat"
    ]

    personnes = charger_personnes()

    personne = personnes.get(
        utilisateur
    )

    memoires = souvenirs_recents(
        utilisateur,
        15
    )

    concepts = charger_concepts()
    lexique = charger_lexique()
    preferences = charger_preferences()

    souvenirs_texte = []

    for memoire in memoires:
        souvenirs_texte.append(
            (
                f"- {memoire.get('message', '')} "
                f"→ {memoire.get('reponse', '')}"
            )
        )

    concepts_texte = []

    for nom, concept in list(
        concepts.items()
    )[-30:]:
        concepts_texte.append(
            f"- {nom} : "
            f"{concept.get('explication', '')}"
        )

    mots_texte = []

    for mot, valeur in list(
        lexique.items()
    )[-40:]:
        mots_texte.append(
            f"- {mot} = "
            f"{valeur.get('definition', '')}"
        )

    personne_texte = (
        "Aucune information personnelle."
    )

    if personne:
        personne_texte = json.dumps(
            personne,
            ensure_ascii=False
        )

    return {
        "etat": etat,
        "personne": personne_texte,
        "souvenirs":
            "\n".join(
                souvenirs_texte
            )
            or "Aucun souvenir.",
        "concepts":
            "\n".join(
                concepts_texte
            )
            or "Aucun concept appris.",
        "lexique":
            "\n".join(
                mots_texte
            )
            or "Aucun mot personnel appris.",
        "preferences":
            json.dumps(
                preferences,
                ensure_ascii=False
            ),
        "motivation":
            determiner_motivation(
                etat
            ),
        "emotion":
            emotion_dominante(
                etat
            )
    }


# ============================================================
# PROMPT COGNITIF
# ============================================================

def construire_prompt(
    utilisateur,
    message,
    contexte
):
    etat = contexte[
        "etat"
    ]

    phase = etat[
        "phase"
    ]

    prompt = f"""

TU ES CHAPPIE.

Tu es le cerveau linguistique d'un projet robotique
qui simule une
