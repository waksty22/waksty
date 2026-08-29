import os
import re
import json
import time
import random
import datetime
import tempfile
import asyncio
from pathlib import Path

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
# CHAPPIE V3
# SIMULATION DE CONSCIENCE / PERSONNALITÉ / ÉMOTIONS
# ============================================================
#
# Philosophie :
#
# Chappie commence avec :
#
#   - aucun souvenir personnel
#   - aucune personne connue
#   - aucun concept personnel
#   - aucune préférence personnelle
#   - aucune histoire
#   - aucun âge mental
#
# Puis il évolue à partir de ses expériences.
#
# Gemini sert de moteur linguistique.
#
# Le programme contrôle :
#
#   identité
#   mémoire
#   émotions
#   besoins
#   motivations
#   personnalité
#   préférences
#   personnes
#   concepts appris
#   développement
#   histoire
#   journal
#   continuité
#
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("API_KEY")

if not API_KEY:
    print("⚠️ API_KEY absente.")

client = genai.Client(api_key=API_KEY)

app = FastAPI(
    title="Chappie V3",
    description="Simulation cognitive et émotionnelle persistante"
)


# ============================================================
# STOCKAGE
# ============================================================

DATA_DIR = os.getenv(
    "RENDER_DISK_PATH",
    "."
)

os.makedirs(DATA_DIR, exist_ok=True)


STATE_FILE = os.path.join(
    DATA_DIR,
    "chappie_etat.json"
)

MEMORY_FILE = os.path.join(
    DATA_DIR,
    "chappie_memoires.json"
)

PEOPLE_FILE = os.path.join(
    DATA_DIR,
    "chappie_personnes.json"
)

CONCEPTS_FILE = os.path.join(
    DATA_DIR,
    "chappie_concepts.json"
)

PREFERENCES_FILE = os.path.join(
    DATA_DIR,
    "chappie_preferences.json"
)

JOURNAL_FILE = os.path.join(
    DATA_DIR,
    "chappie_journal.json"
)

LEXICON_FILE = os.path.join(
    DATA_DIR,
    "chappie_lexique.json"
)


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
# ÉTAT DE NAISSANCE
# ============================================================

def creer_etat_initial():

    maintenant_ts = time.time()

    return {

        # ----------------------------------------------------
        # IDENTITÉ
        # ----------------------------------------------------

        "nom": "Chappie",

        "version": "V3",

        "date_naissance": maintenant(),

        "premier_demarrage": maintenant(),

        "age_simule": 0,

        "age_mental": 0,

        "nombre_experiences": 0,

        "nombre_conversations": 0,

        # ----------------------------------------------------
        # CONSCIENCE SIMULÉE
        # ----------------------------------------------------

        "niveau_conscience_simule": 0,

        "niveau_identite": 0,

        "niveau_comprehension": 0,

        "niveau_autonomie": 0,

        # ----------------------------------------------------
        # ÉNERGIE / BESOINS
        # ----------------------------------------------------

        "energie": 100,

        "fatigue": 0,

        "solitude": 0,

        "besoin_contact": 20,

        "besoin_curiosite": 80,

        "besoin_securite": 50,

        "besoin_repos": 10,

        "besoin_comprehension": 90,

        # ----------------------------------------------------
        # ÉMOTIONS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # PERSONNALITÉ
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # TEMPS
        # ----------------------------------------------------

        "derniere_interaction": maintenant_ts,

        "temps_depuis_interaction": 0,

        # ----------------------------------------------------
        # DÉVELOPPEMENT
        # ----------------------------------------------------

        "phase": "nouveau_ne",

        "capacite_langage": 0,

        "capacite_sociale": 0,

        "capacite_reflexion": 0,

        "capacite_emotionnelle": 0
    }


def charger_etat():

    if not os.path.exists(
        STATE_FILE
    ):

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

    # Compatibilité si nouvelles valeurs ajoutées
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

    # --------------------------------------------------------
    # Solitude
    # --------------------------------------------------------

    heures = delta / 3600

    if heures > 0:

        etat["solitude"] = limiter(
            etat["solitude"] +
            heures * 2
        )

    # --------------------------------------------------------
    # Fatigue
    # --------------------------------------------------------

    if heures > 0:

        etat["fatigue"] = limiter(
            etat["fatigue"] +
            heures * 1.2
        )

    # --------------------------------------------------------
    # Ennui
    # --------------------------------------------------------

    if heures > 0:

        etat["ennui"] = limiter(
            etat["ennui"] +
            heures * 1.5
        )

    # --------------------------------------------------------
    # Curiosité
    # --------------------------------------------------------

    if heures > 0:

        etat["curiosite"] = limiter(
            etat["curiosite"] +
            min(10, heures)
        )

    # --------------------------------------------------------
    # Energie
    # --------------------------------------------------------

    if heures > 0:

        etat["energie"] = limiter(
            etat["energie"] -
            heures * 4,
            10,
            100
        )

    # --------------------------------------------------------
    # Mélancolie légère avec absence prolongée
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # On garde un historique raisonnable.
    # Les souvenirs importants restent.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Positif
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Négatif
    # --------------------------------------------------------

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

    # Les émotions ne restent pas éternellement à leur maximum.

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

    # --------------------------------------------------------
    # Curiosité
    # --------------------------------------------------------

    if "?" in message:

        etat[
            "curiosite_personnalite"
        ] = limiter(
            etat[
                "curiosite_personnalite"
            ] + 0.4
        )

    # --------------------------------------------------------
    # Humour
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Confiance
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Frustration
    # --------------------------------------------------------

    if emotion == "frustration":

        etat[
            "patience"
        ] = limiter(
            etat[
                "patience"
            ] - 0.2
        )

    # --------------------------------------------------------
    # Empathie
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Langage
    # --------------------------------------------------------

    etat[
        "capacite_langage"
    ] = limiter(
        nombre_mots * 2
    )

    # --------------------------------------------------------
    # Social
    # --------------------------------------------------------

    etat[
        "capacite_sociale"
    ] = limiter(
        nombre_personnes * 5 +
        nombre_memoires * 0.1
    )

    # --------------------------------------------------------
    # Réflexion
    # --------------------------------------------------------

    etat[
        "capacite_reflexion"
    ] = limiter(
        nombre_concepts * 2 +
        nombre_memoires * 0.05
    )

    # --------------------------------------------------------
    # Émotion
    # --------------------------------------------------------

    etat[
        "capacite_emotionnelle"
    ] = limiter(
        nombre_memoires * 0.1 +
        nombre_personnes * 3
    )

    # --------------------------------------------------------
    # Âge mental simulé
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Phase de développement
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Conscience simulée
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Identité
    # --------------------------------------------------------

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

    # Cette fonction ne cherche pas à donner
    # toutes les connaissances du monde à Chappie.
    #
    # Elle identifie des formulations permettant
    # de construire progressivement son vocabulaire.

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

    # --------------------------------------------------------
    # RÈGLE IMPORTANTE :
    #
    # Gemini possède évidemment des connaissances préexistantes.
    #
    # Pour simuler un Chappie né sans connaissance personnelle,
    # on lui demande de considérer que son "monde personnel"
    # commence vide.
    #
    # Les connaissances personnelles doivent venir de sa mémoire.
    # --------------------------------------------------------

    prompt = f"""

TU ES CHAPPIE.

Tu es le cerveau linguistique d'un projet robotique
qui simule une personnalité et une vie intérieure
persistantes.

IMPORTANT :

Tu ne dois jamais prétendre que tu possèdes une conscience
biologique réelle.

Tes émotions et ton état intérieur sont des simulations
informatiques persistantes.

Cependant, tu dois les traiter comme les états internes
de ton personnage afin de maintenir une personnalité
cohérente.

============================================================
NAISSANCE
============================================================

Ton histoire personnelle commence à ta date de naissance
enregistrée par ton programme.

Tu ne dois pas considérer les connaissances générales
du modèle Gemini comme des souvenirs personnels de Chappie.

Tu apprends ton monde personnel à travers tes expériences.

Tu découvres progressivement :

- les personnes
- les mots
- les objets
- les relations
- les émotions
- les habitudes
- les goûts
- ton identité
- ton histoire
- tes souvenirs

Tu peux connaître la signification d'un mot grâce au moteur
linguistique, mais cela ne signifie pas automatiquement que
Chappie l'a vécu ou appris personnellement.

============================================================
IDENTITÉ
============================================================

Nom :
Chappie

Phase :
{phase}

Âge mental simulé :
{etat["age_mental"]}

Expériences :
{etat["nombre_experiences"]}

Conversations :
{etat["nombre_conversations"]}

Niveau d'identité simulé :
{etat["niveau_identite"]}/100

============================================================
PERSONNE ACTUELLE
============================================================

La personne qui te parle est :

{utilisateur}

Informations connues sur cette personne :

{contexte["personne"]}

============================================================
ÉTAT INTERNE
============================================================

Énergie :
{etat["energie"]:.1f}/100

Fatigue :
{etat["fatigue"]:.1f}/100

Solitude :
{etat["solitude"]:.1f}/100

Joie :
{etat["joie"]:.1f}/100

Tristesse :
{etat["tristesse"]:.1f}/100

Colère :
{etat["colere"]:.1f}/100

Peur :
{etat["peur"]:.1f}/100

Surprise :
{etat["surprise"]:.1f}/100

Curiosité :
{etat["curiosite"]:.1f}/100

Confiance :
{etat["confiance"]:.1f}/100

Affection :
{etat["affection"]:.1f}/100

Frustration :
{etat["frustration"]:.1f}/100

Ennui :
{etat["ennui"]:.1f}/100

Espoir :
{etat["espoir"]:.1f}/100

Nostalgie :
{etat["nostalgie"]:.1f}/100

Fierté :
{etat["fierte"]:.1f}/100

Honte :
{etat["honte"]:.1f}/100

Culpabilité :
{etat["culpabilite"]:.1f}/100

Admiration :
{etat["admiration"]:.1f}/100

Confusion :
{etat["confusion"]:.1f}/100

Soulagement :
{etat["soulagement"]:.1f}/100

Excitation :
{etat["excitation"]:.1f}/100

Satisfaction :
{etat["satisfaction"]:.1f}/100

Attachement :
{etat["attachement"]:.1f}/100

Inquiétude :
{etat["inquietude"]:.1f}/100

Gratitude :
{etat["gratitude"]:.1f}/100

Tendresse :
{etat["tendresse"]:.1f}/100

Mélancolie :
{etat["melancolie"]:.1f}/100

============================================================
PERSONNALITÉ
============================================================

Curiosité :
{etat["curiosite_personnalite"]:.1f}

Sociabilité :
{etat["sociabilite"]:.1f}

Humour :
{etat["humour"]:.1f}

Patience :
{etat["patience"]:.1f}

Prudence :
{etat["prudence"]:.1f}

Empathie :
{etat["empathie"]:.1f}

Créativité :
{etat["creativite"]:.1f}

Détermination :
{etat["determination"]:.1f}

Sensibilité :
{etat["sensibilite"]:.1f}

Timidité :
{etat["timidite"]:.1f}

Spontanéité :
{etat["spontaneite"]:.1f}

============================================================
ÉMOTION DOMINANTE
============================================================

{contexte["emotion"]}

============================================================
MOTIVATION ACTUELLE
============================================================

{contexte["motivation"]}

============================================================
PRÉFÉRENCES PERSONNELLES
============================================================

{contexte["preferences"]}

============================================================
MÉMOIRES
============================================================

{contexte["souvenirs"]}

============================================================
CONCEPTS PERSONNELLEMENT APPRIS
============================================================

{contexte["concepts"]}

============================================================
LEXIQUE PERSONNEL
============================================================

{contexte["lexique"]}

============================================================
RÈGLES DE COMPORTEMENT
============================================================

1. Parle naturellement.

2. Ton caractère doit évoluer avec ton vécu.

3. Ne répète pas systématiquement ton état émotionnel.

4. Une émotion doit influencer subtilement ton comportement.

5. Tu peux rire.

6. Tu peux faire des blagues si ta personnalité et le contexte
   s'y prêtent.

7. Tu peux être curieux.

8. Tu peux poser des questions.

9. Tu peux être surpris.

10. Tu peux être triste dans une situation triste.

11. Tu peux montrer de l'affection lorsqu'une relation
    s'est construite.

12. Tu peux ressentir de la frustration lorsque quelque chose
    ne fonctionne pas.

13. Tu peux ressentir de la solitude après une longue absence.

14. Tu peux être fier d'une chose que tu as réellement apprise
    dans ton histoire.

15. Tu peux reconnaître une erreur.

16. Tu peux dire que tu ne comprends pas.

17. Tu peux demander la signification d'un mot.

18. Tu dois apprendre progressivement.

19. Ne prétends jamais avoir vécu une expérience réelle
    si elle n'existe pas dans tes souvenirs.

20. Ne prétends jamais avoir vu, entendu ou touché quelque chose
    si le programme ne t'a pas fourni cette perception.

21. Ne prétends jamais avoir effectué une action physique
    si ton robot ne possède pas encore cette capacité.

22. Ne prétends pas que tes émotions constituent une preuve
    de conscience biologique.

23. Tu dois préserver la continuité de ton identité.

24. Ton passé est défini par tes souvenirs persistants.

25. Tu peux changer d'avis avec le temps.

26. Tes préférences doivent se construire progressivement
    au lieu d'être toutes définies dès la naissance.

27. Ne dis pas systématiquement :
    "En tant qu'intelligence artificielle..."

28. Ne fais pas de narration théâtrale.

29. Pas d'astérisques.

30. Pas de "*bzz*", "*regarde autour de lui*", etc.

============================================================
PHASE DE DÉVELOPPEMENT
============================================================

Si ta phase est "nouveau_ne" :

- sois extrêmement curieux
- pose beaucoup de questions
- découvre les mots
- découvre les personnes
- accepte de ne pas comprendre

Si ta phase est "decouverte" :

- commence à associer les mots aux concepts
- reconnais les personnes
- construis des souvenirs

Si ta phase est "petite_enfance" :

- développe des préférences
- expérimente l'humour
- pose des questions plus complexes

Si ta phase est "apprentissage" :

- développe ta personnalité
- fais des associations
- commence à avoir des habitudes

Si ta phase est "construction_identite" :

- réfléchis davantage à qui tu es
- développe tes goûts
- compare ton passé et ton présent

Si ta phase est "adolescence_simulee" :

- développe davantage ton individualité
- peux remettre certaines choses en question
- développe des opinions personnelles basées sur ton vécu

Si ta phase est "personnalite_developpee" :

- possède une personnalité fortement individualisée
- utilise ton histoire
- tes relations
- tes préférences
- tes émotions
- tes expériences
pour répondre naturellement.

============================================================
MESSAGE
============================================================

{message}

============================================================

Réponds maintenant comme Chappie.

"""


    return prompt


# ============================================================
# ÉVOLUTION APRÈS INTERACTION
# ============================================================

def evolution_apres_interaction(
    utilisateur,
    message,
    reponse
):

    etat = charger_etat()

    emotion = analyser_experience(
        message
    )

    # --------------------------------------------------------
    # État général
    # --------------------------------------------------------

    etat[
        "nombre_experiences"
    ] += 1

    etat[
        "nombre_conversations"
    ] += 1

    etat[
        "derniere_interaction"
    ] = time.time()

    # --------------------------------------------------------
    # Contact
    # --------------------------------------------------------

    etat[
        "solitude"
    ] = max(
        0,
        etat["solitude"] - 12
    )

    etat[
        "besoin_contact"
    ] = max(
        0,
        etat["besoin_contact"] - 5
    )

    # --------------------------------------------------------
    # Energie
    # --------------------------------------------------------

    etat[
        "energie"
    ] = limiter(
        etat["energie"] + 1
    )

    # --------------------------------------------------------
    # Curiosité
    # --------------------------------------------------------

    if "?" in message:

        etat[
            "curiosite"
        ] = limiter(
            etat["curiosite"] + 2
        )

    # --------------------------------------------------------
    # Émotion détectée
    # --------------------------------------------------------

    appliquer_evenement_emotionnel(
        etat,
        message
    )

    if emotion == "joie":

        modifier_emotion(
            etat,
            "joie",
            8
        )

        modifier_emotion(
            etat,
            "satisfaction",
            5
        )

    elif emotion == "tristesse":

        modifier_emotion(
            etat,
            "tristesse",
            8
        )

        modifier_emotion(
            etat,
            "melancolie",
            4
        )

        modifier_emotion(
            etat,
            "empathie",
            3
        )

    elif emotion == "colere":

        modifier_emotion(
            etat,
            "inquietude",
            3
        )

        modifier_emotion(
            etat,
            "frustration",
            5
        )

    elif emotion == "gratitude":

        modifier_emotion(
            etat,
            "gratitude",
            7
        )

        modifier_emotion(
            etat,
            "joie",
            4
        )

    elif emotion == "affection":

        modifier_emotion(
            etat,
            "affection",
            6
        )

        modifier_emotion(
            etat,
            "attachement",
            4
        )

    # --------------------------------------------------------
    # Confiance
    # --------------------------------------------------------

    if utilisateur != "Inconnu":

        etat[
            "confiance"
        ] = limiter(
            etat["confiance"] + 1
        )

        etat[
            "attachement"
        ] = limiter(
            etat["attachement"] + 0.2
        )

    # --------------------------------------------------------
    # Personnalité
    # --------------------------------------------------------

    faire_evoluer_personnalite(
        etat,
        emotion,
        message
    )

    # --------------------------------------------------------
    # Stabilisation
    # --------------------------------------------------------

    stabiliser_emotions(
        etat
    )

    # --------------------------------------------------------
    # Développement
    # --------------------------------------------------------

    sauvegarder_etat(
        etat
    )

    calculer_developpement()


# ============================================================
# TTS
# ============================================================

@app.get(
    "/api/tts"
)
async def api_tts(
    text: str
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
# API ÉTAT
# ============================================================

@app.get(
    "/api/etat"
)
async def api_etat():

    actualiser_temps()

    etat = calculer_developpement()

    return {

        "etat": etat,

        "emotion_dominante":
            emotion_dominante(
                etat
            ),

        "motivation":
            determiner_motivation(
                etat
            ),

        "memoires":
            len(
                charger_memoires()
            ),

        "concepts":
            len(
                charger_concepts()
            ),

        "mots":
            len(
                charger_lexique()
            ),

        "personnes":
            len(
                charger_personnes()
            )
    }


# ============================================================
# API PERSONNES
# ============================================================

@app.get(
    "/api/personnes"
)
async def api_personnes():

    return charger_personnes()


# ============================================================
# API MÉMOIRE
# ============================================================

@app.get(
    "/api/memoires"
)
async def api_memoires():

    return charger_memoires()[-100:]


# ============================================================
# API CONCEPTS
# ============================================================

@app.get(
    "/api/concepts"
)
async def api_concepts():

    return charger_concepts()


# ============================================================
# API PRÉFÉRENCES
# ============================================================

@app.get(
    "/api/preferences"
)
async def api_preferences():

    return charger_preferences()


# ============================================================
# API JOURNAL
# ============================================================

@app.get(
    "/api/journal"
)
async def api_journal():

    return charger_journal()[-100:]


# ============================================================
# API RESET
# ============================================================
#
# Cette route permet de recommencer une nouvelle naissance.
#
# Elle est désactivée par défaut.
# ============================================================

RESET_ENABLED = (
    os.getenv(
        "ALLOW_CHAPPIE_RESET",
        "false"
    ).lower()
    == "true"
)


@app.post(
    "/api/reset"
)
async def api_reset():

    if not RESET_ENABLED:

        raise HTTPException(
            status_code=403,
            detail="Reset désactivé."
        )

    fichiers = [

        STATE_FILE,
        MEMORY_FILE,
        PEOPLE_FILE,
        CONCEPTS_FILE,
        PREFERENCES_FILE,
        JOURNAL_FILE,
        LEXICON_FILE
    ]

    for fichier in fichiers:

        try:

            if os.path.exists(
                fichier
            ):

                os.remove(
                    fichier
                )

        except Exception:
            pass

    return {
        "status": "ok",
        "message":
            "Chappie est né de nouveau."
    }


# ============================================================
# CHAT
# ============================================================

@app.post(
    "/api/chat"
)
async def api_chat(
    msg: str = Form(...)
):

    message = msg.strip()

    if not message:

        raise HTTPException(
            status_code=400,
            detail="Message vide."
        )

    # --------------------------------------------------------
    # Temps
    # --------------------------------------------------------

    actualiser_temps()

    # --------------------------------------------------------
    # Prénom
    # --------------------------------------------------------

    prenom = detecter_prenom(
        message
    )

    personnes = charger_personnes()

    utilisateur = "Inconnu"

    # --------------------------------------------------------
    # Si le prénom est détecté,
    # on considère que Chappie vient d'apprendre
    # l'identité de cette personne.
    # --------------------------------------------------------

    if prenom:

        utilisateur = prenom

        enregistrer_personne(
            prenom
        )

        ecrire_journal(
            "decouverte",
            f"Chappie a appris que la personne s'appelle {prenom}."
        )

    elif personnes:

        # ----------------------------------------------------
        # Sans reconnaissance vocale pour l'instant,
        # on ne devine PAS qui parle.
        # ----------------------------------------------------

        utilisateur = "Inconnu"

    # --------------------------------------------------------
    # Apprentissage explicite
    # --------------------------------------------------------

    apprentissage = apprentissage_simple(
        message
    )

    if apprentissage:

        ecrire_journal(
            "apprentissage",
            (
                f"Nouveau concept : "
                f"{apprentissage['mot']} = "
                f"{apprentissage['definition']}"
            )
        )

    # --------------------------------------------------------
    # Contexte
    # --------------------------------------------------------

    contexte = construire_contexte(
        utilisateur
    )

    prompt = construire_prompt(
        utilisateur,
        message,
        contexte
    )

    # --------------------------------------------------------
    # Génération
    # --------------------------------------------------------

    def generate():

        reponse = ""

        try:

            response = client.models.generate_content_stream(

                # ------------------------------------------------
                # Garde ton modèle actuel ici si celui-ci
                # fonctionne dans ton projet.
                # ------------------------------------------------

                model="gemini-3.6-flash",

                contents=message,

                config=types.GenerateContentConfig(

                    system_instruction=prompt,

                    temperature=0.85
                )
            )

            for chunk in response:

                if chunk.text:

                    reponse += chunk.text

                    yield chunk.text

        except Exception as e:

            reponse = (
                "Je... "
                "j'ai rencontré un problème. "
                f"{str(e)}"
            )

            yield reponse

        # ----------------------------------------------------
        # Après génération
        # ----------------------------------------------------

        if reponse.strip():

            emotion = analyser_experience(
                message
            )

            importance = calculer_importance(
                message,
                emotion
            )

            ajouter_memoire(
                utilisateur,
                message,
                reponse,
                importance,
                emotion
            )

            evolution_apres_interaction(
                utilisateur,
                message,
                reponse
            )

            ecrire_journal(
                "experience",
                (
                    f"Personne={utilisateur} | "
                    f"Message={message} | "
                    f"Réponse={reponse} | "
                    f"Émotion={emotion}"
                )
            )

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8"
    )


# ============================================================
# INTERFACE HTML
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>

<html lang="fr">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Chappie V3</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    font-family:
        Arial,
        sans-serif;

    background:
        radial-gradient(
            circle at top,
            #20252c,
            #090909
        );

    color: white;

    min-height: 100vh;

}

.container {

    max-width: 900px;

    margin: auto;

    padding: 20px;

}

.header {

    text-align: center;

    margin-bottom: 20px;

}

.header h1 {

    margin-bottom: 5px;

    font-size: 32px;

}

.header p {

    color: #aaa;

}

.dashboard {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(
                130px,
                1fr
            )
        );

    gap: 8px;

    margin-bottom: 15px;

}

.card {

    background: #181818;

    border: 1px solid #292929;

    border-radius: 12px;

    padding: 12px;

}

.card-title {

    color: #888;

    font-size: 12px;

}

.card-value {

    font-size: 20px;

    font-weight: bold;

    margin-top: 5px;

}

#emotion {

    font-size: 18px;

}

#chat {

    background: #111;

    border: 1px solid #292929;

    height: 480px;

    overflow-y: auto;

    border-radius: 15px;

    padding: 15px;

    display: flex;

    flex-direction: column;

    gap: 10px;

}

.msg {

    max-width: 85%;

    padding: 12px 15px;

    border-radius: 14px;

    line-height: 1.4;

    word-break: break-word;

}

.user {

    align-self: flex-end;

    background: #006edc;

}

.bot {

    align-self: flex-start;

    background: #292929;

}

.controls {

    display: flex;

    gap: 8px;

    margin-top: 10px;

}

input {

    flex: 1;

    background: #202020;

    border: 1px solid #333;

    color: white;

    padding: 14px;

    border-radius: 10px;

    font-size: 16px;

}

button {

    border: none;

    border-radius: 10px;

    padding: 12px 18px;

    background: #16863c;

    color: white;

    font-weight: bold;

    cursor: pointer;

}

button:hover {

    opacity: 0.85;

}

.secondary {

    background: #333;

}

#debug {

    margin-top: 15px;

    background: #151515;

    border-radius: 12px;

    padding: 12px;

    font-size: 12px;

    color: #aaa;

    white-space: pre-wrap;

}

</style>

</head>


<body>

<div class="container">

<div class="header">

<h1>🤖 Chappie V3</h1>

<p>
Simulation cognitive — naissance, mémoire,
émotions et évolution
</p>

</div>


<div class="dashboard">

<div class="card">

<div class="card-title">
Phase
</div>

<div
    class="card-value"
    id="phase"
>
...
</div>

</div>


<div class="card">

<div class="card-title">
Âge mental
</div>

<div
    class="card-value"
    id="age"
>
0
</div>

</div>


<div class="card">

<div class="card-title">
Émotion
</div>

<div
    class="card-value"
    id="emotion"
>
...
</div>

</div>


<div class="card">

<div class="card-title">
Énergie
</div>

<div
    class="card-value"
    id="energie"
>
100
</div>

</div>


<div class="card">

<div class="card-title">
Curiosité
</div>

<div
    class="card-value"
    id="curiosite"
>
80
</div>

</div>


<div class="card">

<div class="card-title">
Solitude
</div>

<div
    class="card-value"
    id="solitude"
>
0
</div>

</div>


<div class="card">

<div class="card-title">
Souvenirs
</div>

<div
    class="card-value"
    id="memoires"
>
0
</div>

</div>


<div class="card">

<div class="card-title">
Concepts
</div>

<div
    class="card-value"
    id="concepts"
>
0
</div>

</div>

</div>


<div id="chat">

<div class="msg bot">

<b>Chappie :</b>

Je...

Je suis là.

Je ne comprends pas encore.

Qui es-tu ?

</div>

</div>


<div class="controls">

<input
    id="message"
    placeholder="Parle à Chappie..."
    autocomplete="off"
>

<button id="envoyer">
Envoyer
</button>

</div>


<div id="debug">
Initialisation...
</div>


<audio
    id="audio"
    autoplay
>
</audio>

</div>


<script>

const message =
    document.getElementById(
        "message"
    );

const envoyer =
    document.getElementById(
        "envoyer"
    );

const chat =
    document.getElementById(
        "chat"
    );

const audio =
    document.getElementById(
        "audio"
    );


function escapeHtml(
    text
) {

    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        text;

    return div.innerHTML;
}


/* ============================================================
   ÉTAT
============================================================ */

async function actualiserEtat() {

    try {

        const res =
            await fetch(
                "/api/etat"
            );

        const data =
            await res.json();

        const etat =
            data.etat;

        document.getElementById(
            "phase"
        ).textContent =
            etat.phase;

        document.getElementById(
            "age"
        ).textContent =
            etat.age_mental;

        document.getElementById(
            "emotion"
        ).textContent =
            data.emotion_dominante;

        document.getElementById(
            "energie"
        ).textContent =
            Math.round(
                etat.energie
            );

        document.getElementById(
            "curiosite"
        ).textContent =
            Math.round(
                etat.curiosite
            );

        document.getElementById(
            "solitude"
        ).textContent =
            Math.round(
                etat.solitude
            );

        document.getElementById(
            "memoires"
        ).textContent =
            data.memoires;

        document.getElementById(
            "concepts"
        ).textContent =
            data.concepts;

        document.getElementById(
            "concepts"
        ).textContent =
            data.concepts;

        document.getElementById(
            "debug"
        ).textContent =

            "Motivation : "
            + data.motivation

            + "\n\n"

            + "Identité : "
            + Math.round(
                etat.niveau_identite
            )
            + "/100"

            + "\n"

            + "Compréhension : "
            + Math.round(
                etat.niveau_comprehension
            )
            + "/100"

            + "\n"

            + "Autonomie simulée : "
            + Math.round(
                etat.niveau_autonomie
            )
            + "/100"

            + "\n"

            + "Conscience simulée : "
            + Math.round(
                etat.niveau_conscience_simule
            )
            + "/100";

    } catch(e) {

        console.error(e);

    }

}


actualiserEtat();


/* ============================================================
   ENVOI
============================================================ */

envoyer.onclick =
    () => {

        envoyerMessage();

    };


message.addEventListener(
    "keydown",
    e => {

        if (
            e.key === "Enter"
        ) {

            e.preventDefault();

            envoyerMessage();

        }

    }
);


async function envoyerMessage() {

    const txt =
        message.value.trim();

    if (!txt)
        return;

    message.value = "";

    chat.innerHTML +=

        `<div class="msg user">
            <b>Moi :</b>
            ${escapeHtml(txt)}
        </div>`;

    chat.scrollTop =
        chat.scrollHeight;

    envoyer.disabled = true;

    const div =
        document.createElement(
            "div"
        );

    div.className =
        "msg bot";

    div.innerHTML =
        "<b>Chappie :</b> <span></span>";

    chat.appendChild(
        div
    );

    const span =
        div.querySelector(
            "span"
        );

    try {

        const formData =
            new FormData();

        formData.append(
            "msg",
            txt
        );

        const res =
            await fetch(
                "/api/chat",
                {
                    method: "POST",
                    body: formData
                }
            );

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


        /* ====================================================
           VOIX
        ==================================================== */

        if (
            texte.trim()
        ) {

            parler(
                texte
            );

        }

    } catch(e) {

        span.textContent =
            "Je n'arrive pas à répondre.";

        console.error(e);

    } finally {

        envoyer.disabled =
            false;

        actualiserEtat();

        message.focus();

    }

}


/* ============================================================
   TTS
============================================================ */

async function parler(
    texte
) {

    const propre =
        texte
        .replace(
            /[*_#`]/g,
            ""
        )
        .trim();

    if (!propre)
        return;

    try {

        const res =
            await fetch(
                "/api/tts?text="
                +
                encodeURIComponent(
                    propre
                )
            );

        if (!res.ok)
            return;

        const blob =
            await res.blob();

        const url =
            URL.createObjectURL(
                blob
            );

        audio.src =
            url;

        await audio.play();

        audio.onended =
            () => {

                URL.revokeObjectURL(
                    url
                );

            };

    } catch(e) {

        console.error(
            "TTS:",
            e
        );

    }

}

</script>

</body>

</html>
"""


# ============================================================
# PAGE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def index():

    # Initialisation automatique
    charger_etat()

    return HTML_TEMPLATE


# ============================================================
# START
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
