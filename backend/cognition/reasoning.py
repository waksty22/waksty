
"""
Chappie V19.3 — Raisonnement et métacognition.

Responsabilités :
- Enregistrement des traces cognitives.
- Suivi des décisions.
- Évaluation du doute décisionnel.
- Audit métacognitif.
- Historique des raisonnements.
- Statistiques cognitives.

Le module ne réalise aucun appel réseau.

Les transactions sont gérées par server.py.
Les fonctions de ce module n'effectuent donc pas de commit explicite.
"""

from __future__ import annotations

import json
import math

from datetime import datetime, timezone
from typing import Any, Optional


# ============================================================
# CONFIGURATION
# ============================================================

COGNITION_VERSION = "19.3"

DEFAULT_CONFIDENCE_THRESHOLD = 0.65
DEFAULT_DOUBT_THRESHOLD = 0.60

DEFAULT_AUDIT_LIMIT = 50

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MAX_TEXT_LENGTH = 12000
MAX_USER_ID_LENGTH = 256
MAX_LIMIT = 500


# ============================================================
# OUTILS
# ============================================================

def utc_now() -> str:
    """Retourne la date UTC au format ISO 8601."""

    return datetime.now(timezone.utc).isoformat()


def _normalize_user_id(user_id: Any) -> str:

    if not isinstance(user_id, str):
        raise ValueError(
            "L'identifiant utilisateur doit être une chaîne."
        )

    user_id = user_id.strip()

    if not user_id:
        raise ValueError(
            "Un identifiant utilisateur est obligatoire."
        )

    if len(user_id) > MAX_USER_ID_LENGTH:
        raise ValueError(
            "L'identifiant utilisateur est trop long."
        )

    return user_id


def _safe_text(
    value: Any,
    default: str = "",
    maximum: int = MAX_TEXT_LENGTH
) -> str:

    if value is None:
        return default

    if not isinstance(value, str):
        value = str(value)

    return value.strip()[:maximum]


def _safe_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float
) -> float:

    if isinstance(value, bool):
        return float(default)

    try:
        number = float(value)

        if not math.isfinite(number):
            return float(default)

        return max(
            minimum,
            min(maximum, number)
        )

    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_limit(
    value: Any,
    default: int = DEFAULT_AUDIT_LIMIT
) -> int:

    if isinstance(value, bool):
        return default

    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return max(
            1,
            min(MAX_LIMIT, int(number))
        )

    except (TypeError, ValueError, OverflowError):
        return default


def _serialize_json(value: Any) -> str:

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str
        )
    except (TypeError, ValueError):
        return "{}"


def _row_to_dict(row: Any) -> dict[str, Any]:
    """
    Convertit une ligne SQLite en dictionnaire.

    Compatible avec :
    - sqlite3.Row ;
    - dict ;
    - tuple ou liste lorsque les clés ne sont pas disponibles.
    """

    if isinstance(row, dict):
        return dict(row)

    if hasattr(row, "keys"):

        try:
            return {
                key: row[key]
                for key in row.keys()
            }
        except (KeyError, TypeError, IndexError):
            pass

    if isinstance(row, (tuple, list)):
        return {
            str(index): value
            for index, value in enumerate(row)
        }

    return {}


def _decode_json(value: Any, default: Any = None) -> Any:

    if default is None:
        default = {}

    if not isinstance(value, str):
        return default

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


# ============================================================
# INITIALISATION DES TABLES
# ============================================================

def init_cognition_tables(db) -> None:
    """
    Initialise les tables de raisonnement et de métacognition.

    Les tables sont créées si elles n'existent pas.
    Cette fonction ne réalise pas de commit explicite.
    """

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cognitive_traces (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT NOT NULL,

            thought_type TEXT NOT NULL,

            context_summary TEXT NOT NULL DEFAULT '',

            decision_made TEXT NOT NULL DEFAULT '',

            confidence REAL NOT NULL DEFAULT 0.5,

            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS
            idx_cognitive_traces_user_date
        ON cognitive_traces(user_id, created_at);

        CREATE INDEX IF NOT EXISTS
            idx_cognitive_traces_user_type
        ON cognitive_traces(user_id, thought_type);


        CREATE TABLE IF NOT EXISTS metacognition_logs (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT NOT NULL,

            audit_type TEXT NOT NULL DEFAULT 'general',

            confidence_average REAL NOT NULL DEFAULT 0.0,

            confidence_trend TEXT NOT NULL DEFAULT 'stable',

            doubt_count INTEGER NOT NULL DEFAULT 0,

            trace_count INTEGER NOT NULL DEFAULT 0,

            findings TEXT NOT NULL DEFAULT '{}',

            recommendations TEXT NOT NULL DEFAULT '{}',

            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS
            idx_metacognition_logs_user_date
        ON metacognition_logs(user_id, created_at);
        """
    )


# ============================================================
# ENREGISTREMENT DES TRACES COGNITIVES
# ============================================================

def log_cognitive_trace(
    db,
    user_id: str,
    thought_type: str,
    context_summary: str,
    decision_made: str,
    confidence: float
) -> dict[str, Any]:
    """
    Enregistre une trace cognitive.

    confidence :
        Valeur comprise entre 0 et 1.

    La confiance est une estimation déclarée.
    Elle ne représente pas une preuve de justesse.
    """

    user_id = _normalize_user_id(user_id)

    thought_type = _safe_text(
        thought_type,
        default="general",
        maximum=100
    )

    context_summary = _safe_text(
        context_summary
    )

    decision_made = _safe_text(
        decision_made
    )

    confidence = _safe_number(
        confidence,
        default=0.5,
        minimum=MIN_CONFIDENCE,
        maximum=MAX_CONFIDENCE
    )

    if not thought_type:
        thought_type = "general"

    created_at = utc_now()

    cursor = db.execute(
        """
        INSERT INTO cognitive_traces (
            user_id,
            thought_type,
            context_summary,
            decision_made,
            confidence,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            thought_type,
            context_summary,
            decision_made,
            confidence,
            created_at
        )
    )

    return {
        "id": cursor.lastrowid,
        "user_id": user_id,
        "thought_type": thought_type,
        "context_summary": context_summary,
        "decision_made": decision_made,
        "confidence": confidence,
        "created_at": created_at
    }


# ============================================================
# ÉVALUATION DU DOUTE DÉCISIONNEL
# ============================================================

def evaluate_decision_doubt(
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> dict[str, Any]:
    """
    Évalue si une décision nécessite davantage de prudence.

    confidence :
        Confiance estimée entre 0 et 1.

    threshold :
        Seuil à partir duquel une décision est considérée
        comme suffisamment confiante pour ne pas déclencher
        automatiquement un doute.

    Retour :
        {
            "confidence": 0.4,
            "threshold": 0.65,
            "requires_doubt": True,
            "doubt_level": "high",
            "recommendation": "..."
        }

    Cette fonction ne vérifie pas la vérité de la décision.
    """

    confidence = _safe_number(
        confidence,
        default=0.5,
        minimum=MIN_CONFIDENCE,
        maximum=MAX_CONFIDENCE
    )

    threshold = _safe_number(
        threshold,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        minimum=MIN_CONFIDENCE,
        maximum=MAX_CONFIDENCE
    )

    requires_doubt = confidence < threshold

    if confidence < 0.35:
        doubt_level = "high"

        recommendation = (
            "La confiance est faible. "
            "Rechercher des informations supplémentaires, "
            "vérifier les hypothèses et éviter une conclusion ferme."
        )

    elif confidence < threshold:
        doubt_level = "moderate"

        recommendation = (
            "La confiance est insuffisante. "
            "Vérifier les éléments essentiels avant de conclure."
        )

    else:
        doubt_level = "low"

        recommendation = (
            "La confiance déclarée est suffisante selon le seuil. "
            "La décision doit néanmoins rester vérifiable."
        )

    return {
        "confidence": round(confidence, 4),

        "threshold": round(threshold, 4),

        "requires_doubt": requires_doubt,

        "doubt_level": doubt_level,

        "recommendation": recommendation,

        "is_verified": False
    }


# ============================================================
# LECTURE DES TRACES COGNITIVES
# ============================================================

def get_cognitive_traces(
    db,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT
) -> list[dict[str, Any]]:
    """Retourne les dernières traces d'un utilisateur."""

    user_id = _normalize_user_id(user_id)
    limit = _safe_limit(limit)

    rows = db.execute(
        """
        SELECT
            id,
            user_id,
            thought_type,
            context_summary,
            decision_made,
            confidence,
            created_at
        FROM cognitive_traces
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    ).fetchall()

    return [
        _row_to_dict(row)
        for row in rows
    ]


# ============================================================
# LECTURE DES AUDITS MÉTACOGNITIFS
# ============================================================

def get_metacognition_logs(
    db,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT
) -> list[dict[str, Any]]:
    """Retourne les derniers audits métacognitifs."""

    user_id = _normalize_user_id(user_id)
    limit = _safe_limit(limit)

    rows = db.execute(
        """
        SELECT
            id,
            user_id,
            audit_type,
            confidence_average,
            confidence_trend,
            doubt_count,
            trace_count,
            findings,
            recommendations,
            created_at
        FROM metacognition_logs
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    ).fetchall()

    results = []

    for row in rows:

        item = _row_to_dict(row)

        item["findings"] = _decode_json(
            item.get("findings"),
            {}
        )

        item["recommendations"] = _decode_json(
            item.get("recommendations"),
            {}
        )

        results.append(item)

    return results


# ============================================================
# AUDIT MÉTACOGNITIF
# ============================================================

def run_metacognitive_audit(
    db,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT
) -> dict[str, Any]:
    """
    Analyse les dernières traces cognitives.

    L'audit mesure :
    - La confiance moyenne déclarée.
    - L'évolution de cette confiance.
    - Le nombre de décisions nécessitant du doute.
    - Les tendances observées dans les traces.

    IMPORTANT :
    Une confiance élevée ne signifie pas qu'un raisonnement
    est juste. La qualité réelle nécessite une vérification
    indépendante des résultats.
    """

    user_id = _normalize_user_id(user_id)
    limit = _safe_limit(limit)

    traces = get_cognitive_traces(
        db,
        user_id,
        limit
    )

    if not traces:

        return {
            "user_id": user_id,
            "audit_type": "general",
            "trace_count": 0,
            "confidence_average": 0.0,
            "confidence_trend": "insufficient_data",
            "doubt_count": 0,
            "findings": {
                "status": "no_data",
                "message": "Aucune trace cognitive disponible."
            },
            "recommendations": {
                "next_step": (
                    "Enregistrer des traces cognitives "
                    "pour permettre un audit."
                )
            },
            "created_at": utc_now()
        }

    confidences = [
        _safe_number(
            trace.get("confidence"),
            default=0.5,
            minimum=MIN_CONFIDENCE,
            maximum=MAX_CONFIDENCE
        )
        for trace in traces
    ]

    confidence_average = (
        sum(confidences) / len(confidences)
    )

    doubt_count = sum(
        1
        for confidence in confidences
        if confidence < DEFAULT_DOUBT_THRESHOLD
    )

    # Les traces sont récupérées de la plus récente
    # à la plus ancienne. On inverse pour analyser
    # l'évolution chronologique.
    chronological = list(reversed(confidences))

    if len(chronological) < 4:

        confidence_trend = "insufficient_data"

    else:

        middle = len(chronological) // 2

        first_half = chronological[:middle]
        second_half = chronological[middle:]

        first_average = (
            sum(first_half) / len(first_half)
        )

        second_average = (
            sum(second_half) / len(second_half)
        )

        difference = second_average - first_average

        if difference > 0.05:
            confidence_trend = "increasing"

        elif difference < -0.05:
            confidence_trend = "decreasing"

        else:
            confidence_trend = "stable"

    # --------------------------------------------------------
    # ANALYSE DES TYPES DE RAISONNEMENT
    # --------------------------------------------------------

    thought_types: dict[str, int] = {}

    for trace in traces:

        thought_type = _safe_text(
            trace.get("thought_type"),
            default="general",
            maximum=100
        ) or "general"

        thought_types[thought_type] = (
            thought_types.get(thought_type, 0) + 1
        )

    # --------------------------------------------------------
    # CONSTATATIONS
    # --------------------------------------------------------

    findings = {
        "confidence_average": round(
            confidence_average,
            4
        ),

        "confidence_trend": confidence_trend,

        "doubt_count": doubt_count,

        "doubt_ratio": round(
            doubt_count / len(traces),
            4
        ),

        "thought_types": thought_types,

        "trend_measure": "confidence_only",

        "reasoning_quality_verified": False
    }

    # --------------------------------------------------------
    # RECOMMANDATIONS
    # --------------------------------------------------------

    recommendations = []

    if confidence_average < DEFAULT_CONFIDENCE_THRESHOLD:

        recommendations.append(
            "Renforcer la vérification des informations "
            "avant de prendre une décision."
        )

    if doubt_count > 0:

        recommendations.append(
            "Analyser les décisions ayant une confiance faible."
        )

    if confidence_trend == "decreasing":

        recommendations.append(
            "Examiner les causes de la baisse de confiance "
            "et identifier les difficultés rencontrées."
        )

    elif confidence_trend == "increasing":

        recommendations.append(
            "Vérifier que la hausse de confiance correspond "
            "à une amélioration réelle des résultats."
        )

    if not recommendations:

        recommendations.append(
            "Continuer à enregistrer les raisonnements "
            "et à vérifier les décisions."
        )

    created_at = utc_now()

    # --------------------------------------------------------
    # ENREGISTREMENT DE L'AUDIT
    # --------------------------------------------------------

    cursor = db.execute(
        """
        INSERT INTO metacognition_logs (
            user_id,
            audit_type,
            confidence_average,
            confidence_trend,
            doubt_count,
            trace_count,
            findings,
            recommendations,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            "general",
            round(confidence_average, 4),
            confidence_trend,
            doubt_count,
            len(traces),
            _serialize_json(findings),
            _serialize_json(recommendations),
            created_at
        )
    )

    return {
        "id": cursor.lastrowid,

        "user_id": user_id,

        "audit_type": "general",

        "trace_count": len(traces),

        "confidence_average": round(
            confidence_average,
            4
        ),

        "confidence_trend": confidence_trend,

        "doubt_count": doubt_count,

        "findings": findings,

        "recommendations": recommendations,

        "created_at": created_at
    }


# ============================================================
# STATISTIQUES COGNITIVES
# ============================================================

def get_cognition_statistics(
    db,
    user_id: str
) -> dict[str, Any]:
    """Retourne les statistiques cognitives d'un utilisateur."""

    user_id = _normalize_user_id(user_id)

    trace_row = db.execute(
        """
        SELECT
            COUNT(*) AS total_traces,
            AVG(confidence) AS average_confidence,
            MIN(confidence) AS minimum_confidence,
            MAX(confidence) AS maximum_confidence
        FROM cognitive_traces
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    trace_stats = _row_to_dict(trace_row)

    audit_row = db.execute(
        """
        SELECT
            COUNT(*) AS total_audits,
            AVG(confidence_average) AS average_audit_confidence,
            SUM(doubt_count) AS total_doubts
        FROM metacognition_logs
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    audit_stats = _row_to_dict(audit_row)

    return {
        "user_id": user_id,

        "version": COGNITION_VERSION,

        "total_traces": int(
            trace_stats.get("total_traces") or 0
        ),

        "average_confidence": round(
            float(trace_stats.get("average_confidence") or 0.0),
            4
        ),

        "minimum_confidence": round(
            float(trace_stats.get("minimum_confidence") or 0.0),
            4
        ),

        "maximum_confidence": round(
            float(trace_stats.get("maximum_confidence") or 0.0),
            4
        ),

        "total_audits": int(
            audit_stats.get("total_audits") or 0
        ),

        "average_audit_confidence": round(
            float(
                audit_stats.get("average_audit_confidence") or 0.0
            ),
            4
        ),

        "total_doubts": int(
            audit_stats.get("total_doubts") or 0
        ),

        "confidence_is_not_accuracy": True
    }
