# Backend/cognition/engine.py

"""
Chappie V19.3 — Moteur cognitif adaptatif.

Responsabilités :
- Calcul du profil cognitif global.
- Calcul des niveaux des 12 systèmes cognitifs.
- Évaluation pondérée des 92 sous-branches.
- Analyse de l'asymétrie cognitive.
- Détection des forces et faiblesses.
- Évaluation de la maturité cognitive.
- Adaptation comportementale.
- Cache isolé par utilisateur.

Le moteur est synchrone et ne réalise aucun appel réseau.

Les données d'apprentissage restent stockées en base.
Le cache ne contient que les résultats calculés.

Format des données attendu :

{
    "tete": {
        "logique_formelle": {
            "level": 1,
            "mastery": 0,
            "confidence": 0.5,
            "xp": 0
        }
    },
    "mots": {
        "vocabulaire": {
            "level": 1,
            "mastery": 0,
            "confidence": 0.5,
            "xp": 0
        }
    }
}
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

ENGINE_VERSION = "21.0"

DEFAULT_LEVEL = 0
DEFAULT_MASTERY = 0.0
DEFAULT_CONFIDENCE = 0.5
DEFAULT_XP = 0

MIN_LEVEL = 0
MAX_LEVEL = 30

MIN_MASTERY = 0.0
MAX_MASTERY = 100.0

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MAX_XP = 10**12

DEFAULT_CACHE_TTL = 60.0

MASTERY_INFLUENCE = 0.15

# Conservées pour compatibilité avec d'éventuels imports.
# La confiance et l'XP ne gonflent pas la maturité.
CONFIDENCE_INFLUENCE = 0.10
XP_INFLUENCE = 0.05

MAX_USER_ID_LENGTH = 256
MAX_WEIGHT = 1000.0

STRENGTHS_LIMIT = 5
WEAKNESSES_LIMIT = 5

# Le calcul global donne le même poids à chaque système.
# Les pondérations ne s'appliquent qu'à l'intérieur du système.


# ============================================================
# VALIDATION DES DONNÉES
# ============================================================

def _safe_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float
) -> float:
    """Convertit une valeur en nombre fini borné."""

    if isinstance(value, bool):
        return float(default)

    try:
        number = float(value)

        if not math.isfinite(number):
            return float(default)

        return max(
            float(minimum),
            min(float(maximum), number)
        )

    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_integer(
    value: Any,
    default: int,
    minimum: int,
    maximum: int
) -> int:
    """Convertit une valeur en entier borné."""

    if isinstance(value, bool):
        return default

    try:
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
    Retourne un poids valide.

    Un poids invalide retourne 0.0 :
    il ne doit jamais être remplacé par 1.0,
    car cela modifierait silencieusement les pondérations.
    """

    if isinstance(value, bool):
        return 0.0

    try:
        number = float(value)

        if not math.isfinite(number):
            return 0.0

        if number <= 0:
            return 0.0

        return min(number, MAX_WEIGHT)

    except (TypeError, ValueError, OverflowError):
        return 0.0


def _normalize_user_id(user_id: Any) -> str:
    """Valide et normalise un identifiant utilisateur."""

    if not isinstance(user_id, str):
        raise ValueError(
            "L'identifiant utilisateur doit être une chaîne."
        )

    normalized = user_id.strip()

    if not normalized:
        raise ValueError(
            "Un identifiant utilisateur est obligatoire."
        )

    if len(normalized) > MAX_USER_ID_LENGTH:
        raise ValueError(
            "L'identifiant utilisateur est trop long."
        )

    return normalized


def _normalize_skill_data(
    data: Any
) -> Dict[str, Any]:
    """
    Normalise les données d'une sous-branche.

    Format :
    {
        "level": 1,
        "mastery": 0,
        "confidence": 0.5,
        "xp": 0
    }
    """

    if not isinstance(data, dict):
        data = {}

    return {
        **data,

        "level": _safe_integer(
            data.get("level", DEFAULT_LEVEL),
            DEFAULT_LEVEL,
            MIN_LEVEL,
            MAX_LEVEL
        ),

        "mastery": _safe_number(
            data.get("mastery", DEFAULT_MASTERY),
            DEFAULT_MASTERY,
            MIN_MASTERY,
            MAX_MASTERY
        ),

        "confidence": _safe_number(
            data.get("confidence", DEFAULT_CONFIDENCE),
            DEFAULT_CONFIDENCE,
            MIN_CONFIDENCE,
            MAX_CONFIDENCE
        ),

        "xp": _safe_integer(
            data.get("xp", DEFAULT_XP),
            DEFAULT_XP,
            0,
            MAX_XP
        )
    }


def _get_catalog_branches(
    system_info: Any
) -> Dict[str, Any]:
    """Retourne les sous-branches d'un système si elles sont valides."""

    if not isinstance(system_info, dict):
        return {}

    branches = system_info.get("sub_branches", {})

    if not isinstance(branches, dict):
        return {}

    return branches


# ============================================================
# SIGNATURE DES DONNÉES POUR LE CACHE
# ============================================================

def _build_skills_fingerprint(
    db_skills_data: Dict[str, Any]
) -> tuple:
    """
    Construit une signature déterministe des données utilisées.

    Une modification de niveau, maîtrise, confiance ou XP
    d'une sous-branche invalide automatiquement le cache.
    """

    if not isinstance(db_skills_data, dict):
        db_skills_data = {}

    fingerprint = []

    for system_id, system_info in COGNITIVE_CATALOG.items():

        if not isinstance(system_id, str):
            continue

        branches = _get_catalog_branches(system_info)

        user_system_data = db_skills_data.get(
            system_id,
            {}
        )

        if not isinstance(user_system_data, dict):
            user_system_data = {}

        system_signature = []

        for branch_id in branches:

            if not isinstance(branch_id, str):
                continue

            normalized = _normalize_skill_data(
                user_system_data.get(branch_id, {})
            )

            system_signature.append((
                branch_id,
                normalized["level"],
                normalized["mastery"],
                normalized["confidence"],
                normalized["xp"]
            ))

        fingerprint.append((
            system_id,
            tuple(system_signature)
        ))

    return tuple(fingerprint)


# ============================================================
# CALCUL DES NIVEAUX EFFECTIFS
# ============================================================

def _calculate_effective_level(
    level: int,
    mastery: float
) -> float:
    """
    Calcule le niveau effectif d'une compétence.

    Le niveau reste compris entre 1 et 30.

    La maîtrise apporte une correction maximale de 0.15.
    La confiance et l'XP sont affichées séparément.
    """

    mastery_bonus = (
        mastery / 100.0
    ) * MASTERY_INFLUENCE

    effective_level = float(level) + mastery_bonus

    return max(
        float(MIN_LEVEL),
        min(float(MAX_LEVEL), effective_level)
    )


# ============================================================
# MOTEUR COGNITIF
# ============================================================

class CognitiveEngine:
    """Moteur de calcul du profil cognitif de Chappie."""

    def __init__(
        self,
        cache_ttl: float = DEFAULT_CACHE_TTL
    ) -> None:

        self._user_caches: Dict[str, Dict[str, Any]] = {}

        self._cache_ttl = _safe_number(
            cache_ttl,
            DEFAULT_CACHE_TTL,
            0.0,
            86400.0
        )

        self._lock = threading.RLock()

    # ========================================================
    # CACHE
    # ========================================================

    def invalidate_cache(
        self,
        user_id: Optional[str] = None
    ) -> None:
        """Invalide le cache d'un utilisateur ou de tous."""

        with self._lock:

            if user_id is not None:

                try:
                    normalized_id = _normalize_user_id(user_id)
                except ValueError:
                    return

                self._user_caches.pop(normalized_id, None)

            else:
                self._user_caches.clear()

    def _get_cached_profile(
        self,
        user_id: str,
        current_time: float,
        fingerprint: tuple
    ) -> Optional[Dict[str, Any]]:

        if self._cache_ttl <= 0:
            return None

        with self._lock:

            cached = self._user_caches.get(user_id)

            if not isinstance(cached, dict):
                return None

            timestamp = cached.get("timestamp", 0.0)

            if (
                not isinstance(timestamp, (int, float))
                or isinstance(timestamp, bool)
                or not math.isfinite(float(timestamp))
            ):
                self._user_caches.pop(user_id, None)
                return None

            if current_time - timestamp >= self._cache_ttl:
                self._user_caches.pop(user_id, None)
                return None

            if cached.get("fingerprint") != fingerprint:
                self._user_caches.pop(user_id, None)
                return None

            profile = cached.get("profile")

            if not isinstance(profile, dict):
                self._user_caches.pop(user_id, None)
                return None

            return copy.deepcopy(profile)

    def _save_cached_profile(
        self,
        user_id: str,
        profile: Dict[str, Any],
        current_time: float,
        fingerprint: tuple
    ) -> None:

        if self._cache_ttl <= 0:
            return

        with self._lock:

            self._user_caches[user_id] = {
                "profile": copy.deepcopy(profile),
                "timestamp": current_time,
                "fingerprint": fingerprint
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
        Calcule le profil cognitif complet.

        db_skills_data doit respecter la structure :

        {
            "tete": {
                "logique_formelle": {
                    "level": 1,
                    "mastery": 0,
                    "confidence": 0.5,
                    "xp": 0
                }
            }
        }
        """

        user_id = _normalize_user_id(user_id)

        if not isinstance(db_skills_data, dict):
            db_skills_data = {}

        cache_time = time.monotonic()
        updated_at = time.time()

        fingerprint = _build_skills_fingerprint(
            db_skills_data
        )

        # ----------------------------------------------------
        # CACHE
        # ----------------------------------------------------

        if not force_recompute:

            cached_profile = self._get_cached_profile(
                user_id,
                cache_time,
                fingerprint
            )

            if cached_profile is not None:
                return cached_profile

        # ----------------------------------------------------
        # CALCUL DES SYSTÈMES
        # ----------------------------------------------------

        systems_profile: Dict[str, Any] = {}

        total_branches = 0
        developed_branches = 0

        all_branch_scores = []
        system_maturity_values = []

        for sys_key, sys_info in COGNITIVE_CATALOG.items():

            if not isinstance(sys_key, str):
                continue

            if not isinstance(sys_info, dict):
                continue

            sub_branches = _get_catalog_branches(sys_info)

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
            system_valid_weight_count = 0

            # ------------------------------------------------
            # SOUS-BRANCHES
            # ------------------------------------------------

            for sub_key, sub_meta in sub_branches.items():

                if not isinstance(sub_key, str):
                    continue

                if not isinstance(sub_meta, dict):
                    sub_meta = {}

                weight = _safe_weight(
                    sub_meta.get("weight")
                )

                sub_data = _normalize_skill_data(
                    user_system_data.get(sub_key, {})
                )

                level = sub_data["level"]
                mastery = sub_data["mastery"]
                confidence = sub_data["confidence"]
                xp = sub_data["xp"]

                effective_level = _calculate_effective_level(
                    level,
                    mastery
                )

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

                total_branches += 1
                system_branch_count += 1

                if level > DEFAULT_LEVEL or mastery > 0 or xp > 0:
                    developed_branches += 1

                system_mastery_sum += mastery
                system_confidence_sum += confidence
                system_xp_sum += xp

                # Une pondération invalide ne participe
                # pas à la moyenne pondérée.
                if weight <= 0:
                    continue

                sys_weighted_sum += effective_level * weight
                sys_weight_total += weight
                system_valid_weight_count += 1

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

            # ------------------------------------------------
            # MOYENNES DU SYSTÈME
            # ------------------------------------------------

            avg_sys_level = (
                sys_weighted_sum / sys_weight_total
                if sys_weight_total > 0
                else float(DEFAULT_LEVEL)
            )

            avg_mastery = (
                system_mastery_sum / system_branch_count
                if system_branch_count > 0
                else DEFAULT_MASTERY
            )

            avg_confidence = (
                system_confidence_sum / system_branch_count
                if system_branch_count > 0
                else DEFAULT_CONFIDENCE
            )

            avg_xp = (
                system_xp_sum / system_branch_count
                if system_branch_count > 0
                else DEFAULT_XP
            )

            if sys_weight_total > 0:
                system_maturity_values.append(avg_sys_level)

            systems_profile[sys_key] = {
                "name": sys_info.get("name", sys_key),

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

                "average_xp": round(
                    avg_xp,
                    2
                ),

                "total_xp": system_xp_sum,

                "branch_count": system_branch_count,

                "valid_weight_count": system_valid_weight_count,

                "sub_branches": sub_branches_scores
            }

        # ----------------------------------------------------
        # MATURITÉ GLOBALE
        # ----------------------------------------------------

        if system_maturity_values:

            global_maturity_score = (
                sum(system_maturity_values)
                / len(system_maturity_values)
            )

        else:
            global_maturity_score = float(DEFAULT_LEVEL)

        global_maturity_score = max(
            float(MIN_LEVEL),
            min(float(MAX_LEVEL), global_maturity_score)
        )

        # ----------------------------------------------------
        # FORCES ET FAIBLESSES
        # ----------------------------------------------------

        strengths, weaknesses = self._derive_strengths_weaknesses(
            all_branch_scores
        )

        # ----------------------------------------------------
        # COMPORTEMENT
        # ----------------------------------------------------

        behavior_traits = self._derive_behavioral_traits(
            systems_profile
        )

        # ----------------------------------------------------
        # DÉVELOPPEMENT
        # ----------------------------------------------------

        development_percentage = (
            developed_branches / total_branches * 100.0
            if total_branches > 0
            else 0.0
        )

        development = {
            "total_branches": total_branches,

            "developed_branches": developed_branches,

            "undeveloped_branches": max(
                0,
                total_branches - developed_branches
            ),

            "development_percentage": round(
                development_percentage,
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
            ),

            "maturity_method": "equal_system_weighted_branches",

            "mastery_influence": MASTERY_INFLUENCE,

            "confidence_affects_maturity": False,

            "xp_affects_maturity": False
        }

        # ----------------------------------------------------
        # PROFIL FINAL
        # ----------------------------------------------------

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

            "updated_at": updated_at
        }

        self._save_cached_profile(
            user_id,
            profile,
            cache_time,
            fingerprint
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
        Identifie les compétences les plus et les moins développées.

        Les listes sont disjointes :
        une compétence ne peut pas être simultanément
        une force et une faiblesse.
        """

        if not branches:
            return [], []

        ordered = sorted(
            branches,
            key=lambda item: (
                item.get("effective_level", 0),
                item.get("mastery", 0),
                item.get("level", 0),
                item.get("system", ""),
                item.get("branch", "")
            ),
            reverse=True
        )

        branch_count = len(ordered)

        selection_count = min(
            STRENGTHS_LIMIT,
            max(1, branch_count // 2)
        )

        strengths = ordered[:selection_count]

        remaining = ordered[selection_count:]

        weaknesses = sorted(
            remaining,
            key=lambda item: (
                item.get("effective_level", 0),
                item.get("mastery", 0),
                item.get("level", 0),
                item.get("system", ""),
                item.get("branch", "")
            )
        )[:WEAKNESSES_LIMIT]

        return (
            copy.deepcopy(strengths),
            copy.deepcopy(weaknesses)
        )

    # ========================================================
    # SYSTÈMES EXTRÊMES
    # ========================================================

    def _get_extreme_system(
        self,
        systems: Dict[str, Any],
        highest: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Retourne le système le plus ou le moins développé."""

        if not systems:
            return None

        valid_systems = [
            (key, value)
            for key, value in systems.items()
            if isinstance(value, dict)
        ]

        if not valid_systems:
            return None

        if highest:

            key, data = max(
                valid_systems,
                key=lambda item: item[1].get(
                    "average_level",
                    DEFAULT_LEVEL
                )
            )

        else:

            key, data = min(
                valid_systems,
                key=lambda item: item[1].get(
                    "average_level",
                    DEFAULT_LEVEL
                )
            )

        return {
            "id": key,
            "name": data.get("name", key),
            "average_level": data.get(
                "average_level",
                float(DEFAULT_LEVEL)
            )
        }

    # ========================================================
    # COMPORTEMENTS DYNAMIQUES
    # ========================================================

    def _derive_behavioral_traits(
        self,
        systems: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Traduit les compétences en paramètres comportementaux.
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
            tete.get("average_level", DEFAULT_LEVEL),
            DEFAULT_LEVEL,
            MIN_LEVEL,
            MAX_LEVEL
        )

        mots_lvl = _safe_number(
            mots.get("average_level", DEFAULT_LEVEL),
            DEFAULT_LEVEL,
            MIN_LEVEL,
            MAX_LEVEL
        )

        lien_lvl = _safe_number(
            lien.get("average_level", DEFAULT_LEVEL),
            DEFAULT_LEVEL,
            MIN_LEVEL,
            MAX_LEVEL
        )

        tete_branches = tete.get("sub_branches", {})
        mots_branches = mots.get("sub_branches", {})

        if not isinstance(tete_branches, dict):
            tete_branches = {}

        if not isinstance(mots_branches, dict):
            mots_branches = {}

        humour_data = _normalize_skill_data(
            mots_branches.get("humour_ironie", {})
        )

        incertitude_data = _normalize_skill_data(
            tete_branches.get("gestion_incertitude", {})
        )

        humour_level = _calculate_effective_level(
            humour_data["level"],
            humour_data["mastery"]
        )

        uncertainty_level = _calculate_effective_level(
            incertitude_data["level"],
            incertitude_data["mastery"]
        )

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
        # VOCABULAIRE
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

        humor_enabled = humour_level >= 4

        humor_description = (
            "Comprend progressivement l'ironie, "
            "les jeux de mots et les plaisanteries."
            if humor_enabled
            else
            "Compréhension encore limitée de l'ironie "
            "et des plaisanteries."
        )

        # ----------------------------------------------------
        # INCERTITUDE
        # ----------------------------------------------------

        if uncertainty_level >= 5:

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
        # RELATION
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

        return {
            "response_complexity": response_complexity,

            "vocabulary_richness": vocabulary_richness,

            "humor_enabled": humor_enabled,

            "humor_description": humor_description,

            "humor_level": round(humour_level, 3),

            "uncertainty_handling": uncertainty_handling,

            "uncertainty_level": round(uncertainty_level, 3),

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
# INSTANCE GLOBALE ET FONCTION DE COMPATIBILITÉ
# ============================================================

cognitive_engine = CognitiveEngine()


def calculate_cognitive_profile(
    user_id: str,
    db_skills_data: Optional[Dict[str, Any]] = None,
    force_recompute: bool = False
) -> Dict[str, Any]:
    """
    Fonction utilitaire globale pour calculer ou récupérer le profil cognitif.
    Permet de résoudre l'importation attendue par server.py.
    """
    if db_skills_data is None:
        # Récupération automatique depuis la base de données si aucun dictionnaire n'est passé
        from server import db_connection # type: ignore
        try:
            with db_connection() as db:
                rows = db.execute(
                    "SELECT skill_name, level, xp, evidence FROM skills WHERE user_id=?",
                    (user_id,)
                ).fetchall()
                db_skills_data = {}
                for row in rows:
                    db_skills_data[row["skill_name"]] = {
                        "default": {
                            "level": row["level"],
                            "xp": row["xp"],
                            "confidence": 0.8
                        }
                    }
        except Exception:
            db_skills_data = {}

    return cognitive_engine.compute_cognitive_profile(
        user_id,
        db_skills_data,
        force_recompute
    )
