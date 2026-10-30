# backend/cognition/engine.py

"""
Chappie V19.3 — Moteur cognitif adaptatif.

Responsabilités :
- Calcul du profil cognitif global.
- Calcul des niveaux des 12 systèmes cognitifs.
- Pondération des sous-branches.
- Analyse de l'asymétrie cognitive.
- Détection des forces et faiblesses.
- Évaluation de la maturité cognitive.
- Adaptation comportementale de Chappie.
- Cache isolé par utilisateur.

Le moteur est volontairement léger et synchrone :
il ne réalise aucun appel réseau et ne bloque pas Gemini Live.

Les données d'apprentissage restent stockées dans la base de données.
Le cache ne contient que des résultats calculés.
"""

from __future__ import annotations

import copy
import math
import threading
import time

from typing import Any, Dict, Optional

from cognition.catalog import COGNITIVE_CATALOG


# ============================================================
# CONFIGURATION
# ============================================================

ENGINE_VERSION = "19.3"

DEFAULT_LEVEL = 1
DEFAULT_MASTERY = 0.0
DEFAULT_CONFIDENCE = 0.5
DEFAULT_XP = 0

MIN_LEVEL = 1
MAX_LEVEL = 30

MIN_MASTERY = 0.0
MAX_MASTERY = 100.0

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MAX_XP = 10**12

DEFAULT_CACHE_TTL = 60.0

# Une branche est considérée comme réellement développée
# lorsque son niveau et sa maîtrise progressent.
MASTERY_INFLUENCE = 0.15
CONFIDENCE_INFLUENCE = 0.10
XP_INFLUENCE = 0.05


# ============================================================
# VALIDATION DES DONNÉES
# ============================================================

def _safe_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float
) -> float:
    """
    Convertit une valeur en nombre avec protection contre :
    - None
    - Les chaînes invalides
    - Les NaN
    - Les infinis
    - Les valeurs hors limites
    """

    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return max(minimum, min(maximum, number))

    except (TypeError, ValueError, OverflowError):
        return default


def _safe_integer(
    value: Any,
    default: int,
    minimum: int,
    maximum: int
) -> int:
    """Convertit une valeur en entier sécurisé."""

    try:
        if isinstance(value, bool):
            return default

        number = float(value)

        if not math.isfinite(number):
            return default

        return max(
            minimum,
            min(maximum, int(number))
        )

    except (TypeError, ValueError, OverflowError):
        return default


def _safe_weight(value: Any) -> float:
    """
    Vérifie le poids d'une sous-branche.

    Un poids nul ou négatif ne contribue pas au calcul.
    """

    weight = _safe_number(
        value,
        default=1.0,
        minimum=0.0,
        maximum=1000.0
    )

    return weight


def _normalize_skill_data(
    data: Any
) -> Dict[str, Any]:
    """
    Normalise les données d'une compétence.

    Format attendu :

    {
        "level": 1,
        "mastery": 0,
        "confidence": 0.5,
        "xp": 0
    }
    """

    if not isinstance(data, dict):
        data = {}

    level = _safe_integer(
        data.get("level", DEFAULT_LEVEL),
        DEFAULT_LEVEL,
        MIN_LEVEL,
        MAX_LEVEL
    )

    mastery = _safe_number(
        data.get("mastery", DEFAULT_MASTERY),
        DEFAULT_MASTERY,
        MIN_MASTERY,
        MAX_MASTERY
    )

    confidence = _safe_number(
        data.get("confidence", DEFAULT_CONFIDENCE),
        DEFAULT_CONFIDENCE,
        MIN_CONFIDENCE,
        MAX_CONFIDENCE
    )

    xp = _safe_integer(
        data.get("xp", DEFAULT_XP),
        DEFAULT_XP,
        0,
        MAX_XP
    )

    return {
        **data,
        "level": level,
        "mastery": mastery,
        "confidence": confidence,
        "xp": xp
    }


# ============================================================
# MOTEUR COGNITIF
# ============================================================

class CognitiveEngine:
    """
    Moteur central de calcul cognitif de Chappie.

    Chaque utilisateur possède son propre cache.

    Le profil cognitif est calculé à partir du catalogue
    et des compétences enregistrées en base de données.
    """

    def __init__(
        self,
        cache_ttl: float = DEFAULT_CACHE_TTL
    ) -> None:

        self._user_caches: Dict[str, Dict[str, Any]] = {}

        self._cache_ttl = max(
            0.0,
            _safe_number(
                cache_ttl,
                DEFAULT_CACHE_TTL,
                0.0,
                86400.0
            )
        )

        # Protège le cache si plusieurs requêtes arrivent simultanément.
        self._lock = threading.RLock()

    # ========================================================
    # CACHE
    # ========================================================

    def invalidate_cache(
        self,
        user_id: Optional[str] = None
    ) -> None:
        """
        Invalide le cache d'un utilisateur.

        Sans user_id, tous les caches sont supprimés.
        """

        with self._lock:

            if user_id is not None:
                self._user_caches.pop(str(user_id), None)

            else:
                self._user_caches.clear()

    def _get_cached_profile(
        self,
        user_id: str,
        current_time: float
    ) -> Optional[Dict[str, Any]]:
        """Récupère un profil en cache s'il est encore valide."""

        with self._lock:

            cached = self._user_caches.get(user_id)

            if not cached:
                return None

            timestamp = cached.get("timestamp", 0.0)

            if current_time - timestamp >= self._cache_ttl:
                self._user_caches.pop(user_id, None)
                return None

            # Retourne une copie pour empêcher une modification
            # accidentelle du profil conservé dans le cache.
            return copy.deepcopy(cached["profile"])

    def _save_cached_profile(
        self,
        user_id: str,
        profile: Dict[str, Any],
        current_time: float
    ) -> None:
        """Enregistre le profil cognitif dans le cache."""

        with self._lock:

            self._user_caches[user_id] = {
                "profile": copy.deepcopy(profile),
                "timestamp": current_time
            }

    # ========================================================
    # CALCUL DU PROFIL COGNITIF
    # ========================================================

    def compute_cognitive_profile(
        self,
        user_id: str,
        db_skills_data: Dict[str, Any],
        force_recompute: bool = False
    ) -> Dict[str, Any]:
        """
        Calcule le profil cognitif complet de Chappie.

        Paramètres :
            user_id :
                Identifiant de l'utilisateur.

            db_skills_data :
                Compétences récupérées depuis la base.

            force_recompute :
                Ignore le cache et recalcule le profil.

        Retour :
            {
                "version": "19.3",
                "global_maturity": 1.0,
                "systems": {},
                "behavior": {},
                "strengths": [],
                "weaknesses": [],
                "development": {},
                "updated_at": ...
            }

        Structure attendue des données :

            {
                "tete": {
                    "raisonnement": {
                        "level": 2,
                        "mastery": 30,
                        "confidence": 0.7,
                        "xp": 120
                    }
                }
            }
        """

        user_id = str(user_id or "").strip()

        if not user_id:
            raise ValueError(
                "Un identifiant utilisateur est obligatoire."
            )

        if not isinstance(db_skills_data, dict):
            db_skills_data = {}

        current_time = time.time()

        # ----------------------------------------------------
        # CACHE
        # ----------------------------------------------------

        if not force_recompute:

            cached_profile = self._get_cached_profile(
                user_id,
                current_time
            )

            if cached_profile is not None:
                return cached_profile

        # ----------------------------------------------------
        # CALCUL
        # ----------------------------------------------------

        systems_profile: Dict[str, Any] = {}

        total_weighted_level = 0.0
        total_weights_sum = 0.0

        total_branches = 0
        developed_branches = 0

        all_branch_scores = []

        for sys_key, sys_info in COGNITIVE_CATALOG.items():

            if not isinstance(sys_info, dict):
                continue

            sub_branches = sys_info.get(
                "sub_branches",
                {}
            )

            if not isinstance(sub_branches, dict):
                sub_branches = {}

            user_system_data = db_skills_data.get(
                sys_key,
                {}
            )

            if not isinstance(user_system_data, dict):
                user_system_data = {}

            sub_branches_scores = {}

            sys_weighted_sum = 0.0
            sys_weight_total = 0.0

            system_mastery_sum = 0.0
            system_confidence_sum = 0.0
            system_xp_sum = 0

            system_branch_count = 0

            for sub_key, sub_meta in sub_branches.items():

                if not isinstance(sub_meta, dict):
                    sub_meta = {}

                weight = _safe_weight(
                    sub_meta.get("weight", 1.0)
                )

                raw_data = user_system_data.get(
                    sub_key,
                    {}
                )

                sub_data = _normalize_skill_data(
                    raw_data
                )

                level = sub_data["level"]
                mastery = sub_data["mastery"]
                confidence = sub_data["confidence"]
                xp = sub_data["xp"]

                # ------------------------------------------------
                # SCORE DE DÉVELOPPEMENT
                # ------------------------------------------------

                # Le niveau représente la progression générale.
                # La maîtrise affine l'évaluation de la compétence.
                #
                # La confiance est une mesure de fiabilité déclarée,
                # et non une preuve que la compétence est acquise.
                #
                # L'XP permet de suivre l'expérience accumulée.

                normalized_mastery = mastery / 100.0

                normalized_xp = min(
                    1.0,
                    xp / 10000.0
                )

                mastery_bonus = (
                    normalized_mastery * MASTERY_INFLUENCE
                )

                confidence_bonus = (
                    confidence * CONFIDENCE_INFLUENCE
                )

                xp_bonus = (
                    normalized_xp * XP_INFLUENCE
                )

                # Le niveau reste la donnée principale.
                # Les autres données affinent le score.
                effective_level = (
                    float(level)
                    + mastery_bonus
                    + confidence_bonus
                    + xp_bonus
                )

                effective_level = min(
                    float(MAX_LEVEL),
                    effective_level
                )

                # ------------------------------------------------
                # DONNÉES DE LA SOUS-BRANCHE
                # ------------------------------------------------

                branch_result = {
                    **sub_data,
                    "effective_level": round(
                        effective_level,
                        3
                    ),
                    "weight": weight,
                    "name": sub_meta.get(
                        "name",
                        sub_key
                    )
                }

                sub_branches_scores[sub_key] = branch_result

                if weight > 0:

                    sys_weighted_sum += (
                        effective_level * weight
                    )

                    sys_weight_total += weight

                    system_mastery_sum += mastery
                    system_confidence_sum += confidence
                    system_xp_sum += xp

                    system_branch_count += 1

                    total_branches += 1

                    if level > 1 or mastery > 0 or xp > 0:
                        developed_branches += 1

                    all_branch_scores.append({
                        "system": sys_key,
                        "system_name": sys_info.get(
                            "name",
                            sys_key
                        ),
                        "branch": sub_key,
                        "branch_name": sub_meta.get(
                            "name",
                            sub_key
                        ),
                        "level": level,
                        "effective_level": round(
                            effective_level,
                            3
                        ),
                        "mastery": mastery,
                        "confidence": confidence,
                        "xp": xp,
                        "weight": weight
                    })

            # ----------------------------------------------------
            # MOYENNES DU SYSTÈME
            # ----------------------------------------------------

            avg_sys_level = (
                sys_weighted_sum / sys_weight_total
                if sys_weight_total > 0
                else float(DEFAULT_LEVEL)
            )

            avg_mastery = (
                system_mastery_sum / system_branch_count
                if system_branch_count > 0
                else 0.0
            )

            avg_confidence = (
                system_confidence_sum / system_branch_count
                if system_branch_count > 0
                else DEFAULT_CONFIDENCE
            )

            systems_profile[sys_key] = {
                "name": sys_info.get(
                    "name",
                    sys_key
                ),

                "average_level": round(
                    avg_sys_level,
                    2
                ),

                "average_mastery": round(
                    avg_mastery,
                    2
                ),

                "average_confidence": round(
                    avg_confidence,
                    3
                ),

                "total_xp": system_xp_sum,

                "branch_count": system_branch_count,

                "sub_branches": sub_branches_scores
            }

            total_weighted_level += sys_weighted_sum
            total_weights_sum += sys_weight_total

        # --------------------------------------------------------
        # MATURITÉ COGNITIVE GLOBALE
        # --------------------------------------------------------

        global_maturity_score = (
            total_weighted_level / total_weights_sum
            if total_weights_sum > 0
            else float(DEFAULT_LEVEL)
        )

        # --------------------------------------------------------
        # FORCES ET FAIBLESSES
        # --------------------------------------------------------

        strengths, weaknesses = self._derive_strengths_weaknesses(
            all_branch_scores
        )

        # --------------------------------------------------------
        # COMPORTEMENT
        # --------------------------------------------------------

        behavior_traits = self._derive_behavioral_traits(
            systems_profile
        )

        # --------------------------------------------------------
        # DÉVELOPPEMENT
        # --------------------------------------------------------

        development = {
            "total_branches": total_branches,

            "developed_branches": developed_branches,

            "development_percentage": round(
                (
                    developed_branches / total_branches * 100
                ) if total_branches else 0.0,
                2
            ),

            "systems_count": len(systems_profile),

            "strongest_system": self._get_extreme_system(
                systems_profile,
                highest=True
            ),

            "weakest_system": self._get_extreme_system(
                systems_profile,
                highest=False
            )
        }

        # --------------------------------------------------------
        # PROFIL FINAL
        # --------------------------------------------------------

        profile = {
            "version": ENGINE_VERSION,

            "global_maturity": round(
                global_maturity_score,
                2
            ),

            "systems": systems_profile,

            "behavior": behavior_traits,

            "strengths": strengths,

            "weaknesses": weaknesses,

            "development": development,

            "updated_at": current_time
        }

        # --------------------------------------------------------
        # CACHE
        # --------------------------------------------------------

        self._save_cached_profile(
            user_id,
            profile,
            current_time
        )

        return copy.deepcopy(profile)

    # ========================================================
    # FORCES ET FAIBLESSES
    # ========================================================

    def _derive_strengths_weaknesses(
        self,
        branches: list[Dict[str, Any]]
    ) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
        """
        Identifie les compétences les plus développées
        et les domaines qui nécessitent davantage d'apprentissage.

        Cette asymétrie permet à Chappie d'avoir des profils
        de compétences différents selon les domaines.
        """

        if not branches:
            return [], []

        ordered = sorted(
            branches,
            key=lambda item: item.get(
                "effective_level",
                0
            ),
            reverse=True
        )

        strengths = ordered[:5]

        weaknesses = sorted(
            branches,
            key=lambda item: (
                item.get("effective_level", 0),
                item.get("mastery", 0)
            )
        )[:5]

        return (
            copy.deepcopy(strengths),
            copy.deepcopy(weaknesses)
        )

    # ========================================================
    # IDENTIFICATION DES SYSTÈMES EXTRÊMES
    # ========================================================

    def _get_extreme_system(
        self,
        systems: Dict[str, Any],
        highest: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Retourne le système le plus fort ou le plus faible."""

        if not systems:
            return None

        valid_systems = [
            (key, value)
            for key, value in systems.items()
            if isinstance(value, dict)
        ]

        if not valid_systems:
            return None

        key, data = (
            max(
                valid_systems,
                key=lambda item: item[1].get(
                    "average_level",
                    0
                )
            )
            if highest
            else min(
                valid_systems,
                key=lambda item: item[1].get(
                    "average_level",
                    0
                )
            )
        )

        return {
            "id": key,
            "name": data.get("name", key),
            "average_level": data.get("average_level", 1.0)
        }

    # ========================================================
    # COMPORTEMENTS DYNAMIQUES
    # ========================================================

    def _derive_behavioral_traits(
        self,
        systems: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Traduit les compétences en comportements concrets.

        Ces informations peuvent être injectées dans le prompt
        de Gemini pour adapter les réponses de Chappie.

        Attention :
        ces caractéristiques influencent le comportement généré,
        mais ne constituent pas une conscience réelle.
        """

        tete = systems.get("tete", {})
        mots = systems.get("mots", {})
        lien = systems.get("lien", {})

        if not isinstance(tete, dict):
            tete = {}

        if not isinstance(mots, dict):
            mots = {}

        if not isinstance(lien, dict):
            lien = {}

        tete_lvl = _safe_number(
            tete.get("average_level", 1.0),
            1.0,
            1.0,
            MAX_LEVEL
        )

        mots_lvl = _safe_number(
            mots.get("average_level", 1.0),
            1.0,
            1.0,
            MAX_LEVEL
        )

        lien_lvl = _safe_number(
            lien.get("average_level", 1.0),
            1.0,
            1.0,
            MAX_LEVEL
        )

        tete_branches = tete.get(
            "sub_branches",
            {}
        )

        mots_branches = mots.get(
            "sub_branches",
            {}
        )

        if not isinstance(tete_branches, dict):
            tete_branches = {}

        if not isinstance(mots_branches, dict):
            mots_branches = {}

        humour = _normalize_skill_data(
            mots_branches.get("humour_ironie", {})
        )

        incertitude = _normalize_skill_data(
            tete_branches.get("gestion_incertitude", {})
        )

        humour_lvl = humour["level"]
        incertitude_lvl = incertitude["level"]

        # ----------------------------------------------------
        # COMPLEXITÉ DES RÉPONSES
        # ----------------------------------------------------

        if tete_lvl > 6:
            response_complexity = "expert"

        elif tete_lvl > 3:
            response_complexity = "intermediate"

        else:
            response_complexity = "simple"

        # ----------------------------------------------------
        # RICHESSE DU VOCABULAIRE
        # ----------------------------------------------------

        if mots_lvl > 6:
            vocabulary_richness = "high"

        elif mots_lvl > 3:
            vocabulary_richness = "moderate"

        else:
            vocabulary_richness = "basic"

        # ----------------------------------------------------
        # HUMOUR
        # ----------------------------------------------------

        humor_enabled = humour_lvl >= 4

        humor_description = (
            "Comprend progressivement l'ironie, "
            "les jeux de mots et les plaisanteries."
            if humor_enabled
            else
            "Compréhension encore limitée de l'ironie "
            "et des plaisanteries."
        )

        # ----------------------------------------------------
        # GESTION DE L'INCERTITUDE
        # ----------------------------------------------------

        if incertitude_lvl >= 5:

            uncertainty_handling = (
                "Admet ses lacunes, distingue les faits "
                "des hypothèses et pose des questions "
                "lorsqu'une information manque."
            )

        else:

            uncertainty_handling = (
                "La gestion de l'incertitude est encore "
                "en développement. Doit privilégier "
                "les questions et éviter les affirmations "
                "sans preuve."
            )

        # ----------------------------------------------------
        # EMPATHIE ET RELATION
        # ----------------------------------------------------

        if lien_lvl > 5:

            empathy_depth = (
                "Lecture plus fine des intentions, "
                "du contexte relationnel et adaptation "
                "du soutien apporté."
            )

        else:

            empathy_depth = (
                "Relation directe et factuelle. "
                "La compréhension des intentions et "
                "des émotions reste en développement."
            )

        # ----------------------------------------------------
        # PROFIL COMPORTEMENTAL
        # ----------------------------------------------------

        return {
            "response_complexity": response_complexity,

            "vocabulary_richness": vocabulary_richness,

            "humor_enabled": humor_enabled,

            "humor_description": humor_description,

            "humor_level": humour_lvl,

            "uncertainty_handling": uncertainty_handling,

            "uncertainty_level": incertitude_lvl,

            "empathy_depth": empathy_depth,

            "cognitive_level": round(tete_lvl, 2),

            "language_level": round(mots_lvl, 2),

            "social_level": round(lien_lvl, 2),

            "developmental_adaptation": True,

            "important_rule": (
                "Ne jamais prétendre maîtriser une compétence "
                "qui n'est pas suffisamment développée. "
                "Privilégier les explications adaptées au niveau "
                "réel de Chappie."
            )
        }


# ============================================================
# INSTANCE GLOBALE
# ============================================================

cognitive_engine = CognitiveEngine()



