
"""
Catalogue officiel des 12 Systèmes Cognitifs et de leurs sous-branches
pour Chappie V19.3.

Définit :
- Les 12 systèmes cognitifs.
- Leur arborescence asymétrique.
- Les sous-branches spécialisées.
- Les pondérations relatives.
- Les outils de consultation et de validation du catalogue.

Les 6 socles historiques :
    tete, mots, lien, mains, ame, sens

Les 6 moteurs invisibles :
    attention, apprentissage, memoire, decision, motivation, metacognition

IMPORTANT :
Les pondérations expriment l'importance relative d'une compétence
dans le calcul cognitif. Elles ne représentent pas directement
un niveau de développement ou une mesure scientifique d'intelligence.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional


CATALOG_VERSION = "19.3"


# ============================================================
# CATALOGUE COGNITIF OFFICIEL
# ============================================================

COGNITIVE_CATALOG: dict[str, dict[str, Any]] = {

    # ========================================================
    # LES 6 SOCLES HISTORIQUES
    # ========================================================

    "tete": {
        "name": "Tête — Raisonnement et contrôle cognitif",
        "sub_branches": {

            "logique_formelle": {
                "name": "Logique formelle et déductive",
                "weight": 1.0,
            },

            "logique_inductive": {
                "name": "Raisonnement inductif et probabiliste",
                "weight": 1.0,
            },

            "raisonnement_causal": {
                "name": "Raisonnement causal",
                "weight": 1.2,
            },

            "decomposition": {
                "name": "Décomposition des problèmes complexes",
                "weight": 1.0,
            },

            "planification_mentale": {
                "name": "Planification mentale et anticipation",
                "weight": 1.2,
            },

            "autocorrection": {
                "name": "Détection et correction des erreurs",
                "weight": 1.5,
            },

            "gestion_incertitude": {
                "name": "Gestion de l'incertitude",
                "weight": 1.2,
            },

            "flexibilite": {
                "name": "Flexibilité cognitive",
                "weight": 1.0,
            },

            "abstraction": {
                "name": "Abstraction et généralisation",
                "weight": 1.0,
            },

            "metacognition": {
                "name": "Métacognition (évaluation de soi)",
                "weight": 1.5,
            },
        },
    },

    "mots": {
        "name": "Mots — Langage et communication",
        "sub_branches": {

            "vocabulaire": {
                "name": "Acquisition du vocabulaire",
                "weight": 1.0,
            },

            "syntaxe": {
                "name": "Grammaire et syntaxe",
                "weight": 1.0,
            },

            "contexte_sens": {
                "name": "Compréhension du sens et du contexte",
                "weight": 1.2,
            },

            "construction_phrases": {
                "name": "Construction de phrases",
                "weight": 1.0,
            },

            "metaphores": {
                "name": "Compréhension des métaphores",
                "weight": 1.2,
            },

            "humour_ironie": {
                "name": "Humour, ironie et second degré",
                "weight": 1.5,
            },

            "expressions": {
                "name": "Expressions familières",
                "weight": 1.0,
            },

            "art_question": {
                "name": "Capacité à poser des questions",
                "weight": 1.2,
            },

            "narration": {
                "name": "Narration et explication",
                "weight": 1.0,
            },

            "adaptation_langage": {
                "name": "Adaptation au niveau d'autrui",
                "weight": 1.2,
            },

            "sous_entendus": {
                "name": "Compréhension des sous-entendus",
                "weight": 1.5,
            },
        },
    },

    "lien": {
        "name": "Lien — Relations et cognition sociale",
        "sub_branches": {

            "reconnaissance_emotions": {
                "name": "Reconnaissance des émotions",
                "weight": 1.0,
            },

            "intentions": {
                "name": "Inférence des intentions",
                "weight": 1.2,
            },

            "roles_sociaux": {
                "name": "Compréhension des rôles sociaux",
                "weight": 1.0,
            },

            "point_de_vue": {
                "name": "Prise en compte du point de vue d'autrui",
                "weight": 1.2,
            },

            "empathie_cognitive": {
                "name": "Empathie cognitive",
                "weight": 1.5,
            },

            "soutien": {
                "name": "Réponse de soutien adaptée",
                "weight": 1.0,
            },

            "gestion_desaccords": {
                "name": "Gestion des désaccords",
                "weight": 1.2,
            },

            "reparation_sociale": {
                "name": "Réparation des malentendus",
                "weight": 1.5,
            },

            "limites_consentement": {
                "name": "Compréhension des limites",
                "weight": 1.5,
            },

            "confiance_calibree": {
                "name": "Confiance calibrée",
                "weight": 1.2,
            },

            "reciprocite": {
                "name": "Réciprocité et coopération",
                "weight": 1.0,
            },
        },
    },

    "mains": {
        "name": "Mains — Exécution et résolution pratique",
        "sub_branches": {

            "decomposition_tache": {
                "name": "Décomposition d'une tâche",
                "weight": 1.0,
            },

            "utilisation_outils": {
                "name": "Utilisation des outils disponibles",
                "weight": 1.2,
            },

            "programmation_debug": {
                "name": "Programmation et débogage",
                "weight": 1.5,
            },

            "erreurs_systeme": {
                "name": "Compréhension des erreurs système",
                "weight": 1.2,
            },

            "tests_verification": {
                "name": "Vérification et tests unitaires",
                "weight": 1.5,
            },

            "organisation_projet": {
                "name": "Organisation d'un projet",
                "weight": 1.2,
            },

            "essai_erreur": {
                "name": "Apprentissage par essais et erreurs",
                "weight": 1.0,
            },

            "choix_methodes": {
                "name": "Choix entre plusieurs méthodes",
                "weight": 1.2,
            },

            "gestion_echecs": {
                "name": "Gestion des échecs et reprise",
                "weight": 1.5,
            },

            "respect_limites": {
                "name": "Respect des autorisations",
                "weight": 2.0,
            },
        },
    },

    "ame": {
        "name": "Âme — Créativité et préférences",
        "sub_branches": {

            "association_idees": {
                "name": "Association d'idées",
                "weight": 1.0,
            },

            "imagination": {
                "name": "Imagination de scénarios",
                "weight": 1.2,
            },

            "metaphores_recits": {
                "name": "Création de récits et métaphores",
                "weight": 1.2,
            },

            "sensibilite_musicale": {
                "name": "Sensibilité aux structures sonores",
                "weight": 1.5,
            },

            "gouts_persistants": {
                "name": "Goûts artistiques persistants",
                "weight": 1.2,
            },

            "audace_creative": {
                "name": "Originalité et audace",
                "weight": 1.5,
            },

            "combinaison_concepts": {
                "name": "Combinaison de concepts éloignés",
                "weight": 1.5,
            },

            "autocritique_art": {
                "name": "Évaluation et révision d'une création",
                "weight": 1.2,
            },
        },
    },

    "sens": {
        "name": "Sens — Perception et ancrage dans le monde",
        "sub_branches": {

            "reconnaissance_visuelle": {
                "name": "Reconnaissance visuelle d'objets",
                "weight": 1.0,
            },

            "localisation_spatiale": {
                "name": "Localisation et relations spatiales",
                "weight": 1.2,
            },

            "analyse_mouvements": {
                "name": "Analyse des mouvements",
                "weight": 1.0,
            },

            "perception_auditive": {
                "name": "Perception auditive (Live vocal)",
                "weight": 1.5,
            },

            "sons_non_verbaux": {
                "name": "Reconnaissance des sons non verbaux",
                "weight": 1.0,
            },

            "attention_details": {
                "name": "Attention aux détails pertinents",
                "weight": 1.2,
            },

            "observation_vs_hypothese": {
                "name": "Dissociation observation / supposition",
                "weight": 2.0,
            },

            "fiabilite_perception": {
                "name": "Estimation de la fiabilité perceptive",
                "weight": 1.5,
            },
        },
    },

    # ========================================================
    # LES 6 MOTEURS INVISIBLES
    # ========================================================

    "attention": {
        "name": "Attention — Ce que Chappie remarque",
        "sub_branches": {

            "selection_info": {
                "name": "Sélection des infos pertinentes",
                "weight": 1.2,
            },

            "attention_soutenue": {
                "name": "Attention soutenue",
                "weight": 1.0,
            },

            "alternance_taches": {
                "name": "Alternance entre plusieurs tâches",
                "weight": 1.2,
            },

            "resistance_distractions": {
                "name": "Résistance aux distractions",
                "weight": 1.5,
            },

            "detection_nouveautes": {
                "name": "Détection des nouveautés",
                "weight": 1.0,
            },

            "gestion_contexte": {
                "name": "Gestion de la fenêtre de contexte",
                "weight": 1.5,
            },
        },
    },

    "apprentissage": {
        "name": "Apprentissage — Comment Chappie progresse",
        "sub_branches": {

            "enseignement_explicite": {
                "name": "Apprentissage par enseignement",
                "weight": 1.0,
            },

            "imitation": {
                "name": "Apprentissage par observation",
                "weight": 1.0,
            },

            "experience_directe": {
                "name": "Apprentissage par expérience",
                "weight": 1.2,
            },

            "generalisation": {
                "name": "Généralisation à des situations neuves",
                "weight": 1.5,
            },

            "transfert_competences": {
                "name": "Transfert entre domaines",
                "weight": 2.0,
            },

            "desapprentissage": {
                "name": "Désapprentissage d'une règle fausse",
                "weight": 2.0,
            },
        },
    },

    "memoire": {
        "name": "Mémoire — Ce qu'il conserve et retrouve",
        "sub_branches": {

            "memoire_travail": {
                "name": "Mémoire de travail",
                "weight": 1.0,
            },

            "memoire_episodique": {
                "name": "Mémoire épisodique (événements)",
                "weight": 1.2,
            },

            "memoire_autobiographique": {
                "name": "Mémoire autobiographique",
                "weight": 1.5,
            },

            "memoire_semantique": {
                "name": "Mémoire sémantique (faits)",
                "weight": 1.0,
            },

            "rappel_contextuel": {
                "name": "Rappel contextuel",
                "weight": 1.5,
            },

            "provenance_confiance": {
                "name": "Provenance et confiance des souvenirs",
                "weight": 1.8,
            },
        },
    },

    "decision": {
        "name": "Décision — Comment il choisit",
        "sub_branches": {

            "hierarchisation_objectifs": {
                "name": "Hiérarchisation des objectifs",
                "weight": 1.2,
            },

            "comparaison_options": {
                "name": "Comparaison des options",
                "weight": 1.0,
            },

            "evaluation_risques": {
                "name": "Évaluation des risques",
                "weight": 1.5,
            },

            "arbitrage_vitesse_precision": {
                "name": "Arbitrage vitesse / précision",
                "weight": 1.2,
            },

            "decision_incertitude": {
                "name": "Décision sous incertitude",
                "weight": 1.5,
            },

            "validation_sensible": {
                "name": "Demande de validation préalable",
                "weight": 1.8,
            },
        },
    },

    "motivation": {
        "name": "Motivation — Ce qui oriente son activité",
        "sub_branches": {

            "curiosite": {
                "name": "Curiosité pour les inconnues",
                "weight": 1.2,
            },

            "perseverance": {
                "name": "Persévérance et tolérance à l'échec",
                "weight": 1.5,
            },

            "recherche_nouveaute": {
                "name": "Recherche de nouveauté",
                "weight": 1.0,
            },

            "equilibre_exploration": {
                "name": "Équilibre exploration / exploitation",
                "weight": 1.5,
            },

            "gestion_charge": {
                "name": "Gestion de la charge de travail",
                "weight": 1.2,
            },
        },
    },

    "metacognition": {
        "name": "Identité et Métacognition — Conscience de soi",
        "sub_branches": {

            "connaissance_limites": {
                "name": "Reconnaissance de ses limites",
                "weight": 1.8,
            },

            "estimation_confiance": {
                "name": "Calibration de sa confiance",
                "weight": 1.5,
            },

            "coherence_preferences": {
                "name": "Cohérence des préférences",
                "weight": 1.0,
            },

            "revision_croyances": {
                "name": "Révision de ses croyances",
                "weight": 1.8,
            },

            "explication_decisions": {
                "name": "Capacité à expliquer ses choix",
                "weight": 1.5,
            },
        },
    },
}


# ============================================================
# CONFIGURATION DES 12 SYSTÈMES
# ============================================================

HISTORICAL_SYSTEMS = (
    "tete",
    "mots",
    "lien",
    "mains",
    "ame",
    "sens",
)

INVISIBLE_SYSTEMS = (
    "attention",
    "apprentissage",
    "memoire",
    "decision",
    "motivation",
    "metacognition",
)

EXPECTED_SYSTEMS = HISTORICAL_SYSTEMS + INVISIBLE_SYSTEMS


# ============================================================
# CONSULTATION DU CATALOGUE
# ============================================================

def get_total_systems_count() -> int:
    """Renvoie le nombre de systèmes cognitifs."""

    return len(COGNITIVE_CATALOG)


def get_total_sub_branches_count() -> int:
    """Renvoie le nombre total de sous-branches."""

    return sum(
        len(system["sub_branches"])
        for system in COGNITIVE_CATALOG.values()
    )


def get_system(system_id: str) -> Optional[dict[str, Any]]:
    """Récupère un système cognitif par son identifiant."""

    if not isinstance(system_id, str):
        return None

    system_id = system_id.strip().lower()

    system = COGNITIVE_CATALOG.get(system_id)

    if system is None:
        return None

    return deepcopy(system)


def get_sub_branch(
    system_id: str,
    branch_id: str,
) -> Optional[dict[str, Any]]:
    """Récupère une sous-branche précise."""

    if not isinstance(system_id, str):
        return None

    if not isinstance(branch_id, str):
        return None

    system_id = system_id.strip().lower()
    branch_id = branch_id.strip().lower()

    system = COGNITIVE_CATALOG.get(system_id)

    if system is None:
        return None

    branch = system["sub_branches"].get(branch_id)

    if branch is None:
        return None

    result = deepcopy(branch)

    result["id"] = branch_id
    result["system_id"] = system_id
    result["system_name"] = system["name"]

    return result


def get_all_system_ids() -> list[str]:
    """Retourne les identifiants des 12 systèmes."""

    return list(COGNITIVE_CATALOG.keys())


def get_all_sub_branches() -> list[dict[str, Any]]:
    """Retourne toutes les sous-branches sous forme de liste."""

    branches = []

    for system_id, system in COGNITIVE_CATALOG.items():

        for branch_id, branch in system["sub_branches"].items():

            branches.append({
                "id": branch_id,
                "system_id": system_id,
                "system_name": system["name"],
                "name": branch["name"],
                "weight": branch["weight"],
            })

    return branches


# ============================================================
# PONDÉRATIONS
# ============================================================

def get_system_total_weight(system_id: str) -> float:
    """Calcule le poids total des sous-branches d'un système."""

    system = COGNITIVE_CATALOG.get(
        str(system_id).strip().lower()
    )

    if system is None:
        return 0.0

    return round(
        sum(
            float(branch["weight"])
            for branch in system["sub_branches"].values()
        ),
        4,
    )


def get_system_average_weight(system_id: str) -> float:
    """Calcule le poids moyen des sous-branches d'un système."""

    system = COGNITIVE_CATALOG.get(
        str(system_id).strip().lower()
    )

    if system is None:
        return 0.0

    branches = system["sub_branches"]

    if not branches:
        return 0.0

    return round(
        get_system_total_weight(system_id) / len(branches),
        4,
    )


def get_total_catalog_weight() -> float:
    """Calcule la somme des pondérations du catalogue."""

    return round(
        sum(
            float(branch["weight"])
            for system in COGNITIVE_CATALOG.values()
            for branch in system["sub_branches"].values()
        ),
        4,
    )


def get_branch_weight(
    system_id: str,
    branch_id: str,
) -> float:
    """Retourne le poids d'une sous-branche."""

    branch = get_sub_branch(
        system_id,
        branch_id,
    )

    if branch is None:
        return 0.0

    return float(branch["weight"])


# ============================================================
# VALIDATION DU CATALOGUE
# ============================================================

def validate_cognitive_catalog() -> dict[str, Any]:
    """Vérifie la cohérence structurelle du catalogue.

    Contrôle :
    - Les 12 systèmes attendus.
    - Les noms des systèmes.
    - La présence des sous-branches.
    - Les noms et identifiants des branches.
    - La validité des pondérations.
    - Les éventuels doublons d'identifiants de branches.

    Retourne les erreurs sans modifier le catalogue.
    """

    errors: list[str] = []
    warnings: list[str] = []

    actual_systems = set(COGNITIVE_CATALOG.keys())
    expected_systems = set(EXPECTED_SYSTEMS)

    missing_systems = sorted(
        expected_systems - actual_systems
    )

    unexpected_systems = sorted(
        actual_systems - expected_systems
    )

    if missing_systems:
        errors.append(
            f"Systèmes manquants : {', '.join(missing_systems)}"
        )

    if unexpected_systems:
        warnings.append(
            f"Systèmes supplémentaires : {', '.join(unexpected_systems)}"
        )

    seen_branch_ids: dict[str, str] = {}

    for system_id, system in COGNITIVE_CATALOG.items():

        if not isinstance(system, dict):

            errors.append(
                f"{system_id} : définition du système invalide."
            )

            continue

        system_name = system.get("name")

        if not isinstance(system_name, str) or not system_name.strip():

            errors.append(
                f"{system_id} : nom de système absent ou invalide."
            )

        branches = system.get("sub_branches")

        if not isinstance(branches, dict):

            errors.append(
                f"{system_id} : sub_branches doit être un dictionnaire."
            )

            continue

        if not branches:

            errors.append(
                f"{system_id} : aucune sous-branche définie."
            )

            continue

        for branch_id, branch in branches.items():

            if not isinstance(branch_id, str) or not branch_id.strip():

                errors.append(
                    f"{system_id} : identifiant de sous-branche invalide."
                )

                continue

            if branch_id in seen_branch_ids:

                warnings.append(
                    f"Identifiant de branche réutilisé : {branch_id} "
                    f"({seen_branch_ids[branch_id]} et {system_id})."
                )

            else:

                seen_branch_ids[branch_id] = system_id

            if not isinstance(branch, dict):

                errors.append(
                    f"{system_id}.{branch_id} : définition invalide."
                )

                continue

            branch_name = branch.get("name")

            if (
                not isinstance(branch_name, str)
                or not branch_name.strip()
            ):

                errors.append(
                    f"{system_id}.{branch_id} : nom manquant."
                )

            weight = branch.get("weight")

            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
            ):

                errors.append(
                    f"{system_id}.{branch_id} : poids non numérique."
                )

            elif weight <= 0:

                errors.append(
                    f"{system_id}.{branch_id} : le poids doit être positif."
                )

    return {
        "valid": len(errors) == 0,
        "version": CATALOG_VERSION,
        "total_systems": get_total_systems_count(),
        "total_sub_branches": get_total_sub_branches_count(),
        "total_weight": get_total_catalog_weight(),
        "historical_systems": list(HISTORICAL_SYSTEMS),
        "invisible_systems": list(INVISIBLE_SYSTEMS),
        "errors": errors,
        "warnings": warnings,
    }


# ============================================================
# STATISTIQUES DU CATALOGUE
# ============================================================

def get_catalog_statistics() -> dict[str, Any]:
    """Retourne les statistiques détaillées du catalogue."""

    systems = {}

    for system_id, system in COGNITIVE_CATALOG.items():

        branches = system["sub_branches"]

        systems[system_id] = {
            "name": system["name"],
            "sub_branches_count": len(branches),
            "total_weight": get_system_total_weight(system_id),
            "average_weight": get_system_average_weight(system_id),
            "sub_branches": [
                {
                    "id": branch_id,
                    "name": branch["name"],
                    "weight": branch["weight"],
                }
                for branch_id, branch in branches.items()
            ],
        }

    return {
        "version": CATALOG_VERSION,
        "total_systems": get_total_systems_count(),
        "total_sub_branches": get_total_sub_branches_count(),
        "total_weight": get_total_catalog_weight(),
        "historical_systems_count": len(HISTORICAL_SYSTEMS),
        "invisible_systems_count": len(INVISIBLE_SYSTEMS),
        "systems": systems,
    }


# ============================================================
# EXPORT DU CATALOGUE
# ============================================================

def export_cognitive_catalog() -> dict[str, Any]:
    """Retourne une copie complète du catalogue."""

    return {
        "version": CATALOG_VERSION,
        "catalog": deepcopy(COGNITIVE_CATALOG),
        "statistics": get_catalog_statistics(),
    }


# ============================================================
# VALIDATION AU CHARGEMENT
# ============================================================

CATALOG_VALIDATION = validate_cognitive_catalog()

if not CATALOG_VALIDATION["valid"]:

    raise ValueError(
        "Le catalogue cognitif de Chappie est invalide : "
        + " | ".join(CATALOG_VALIDATION["errors"])
    )
