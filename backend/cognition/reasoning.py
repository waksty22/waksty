
"""Module de cognition, de boucle de décision et de métacognition pour Chappie.

Responsabilités :
- Enregistrer les traces de raisonnement.
- Évaluer le doute et le niveau de confiance.
- Recommander une attitude adaptée à l'incertitude.
- Réaliser des audits métacognitifs.
- Détecter les tendances de confiance.
- Conserver un historique immuable des raisonnements.

Important :
La confiance représente une estimation de fiabilité, pas une preuve
de vérité ni une mesure directe de conscience.
"""

from __future__ import annotations

import json
import math
import sqlite3

from datetime import datetime, timezone
from typing import Any, Optional


ENGINE_VERSION = "19.3"

DEFAULT_CONFIDENCE_THRESHOLD = 0.60
DEFAULT_DOUBT_THRESHOLD = 0.40

DEFAULT_AUDIT_LIMIT = 10
MAX_AUDIT_LIMIT = 500

VALID_THOUGHT_TYPES = {
    "observation",
    "analysis",
    "hypothesis",
    "decision",
    "reflection",
    "memory",
    "learning",
    "prediction",
    "comparison",
    "correction",
    "planning",
    "general",
}


# ============================================================
# UTILITAIRES
# ============================================================

def utc_now() -> str:
    """Retourne la date actuelle en UTC au format ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _clean_text(
    value: Any,
    field_name: str,
    max_length: int = 10000,
    allow_empty: bool = False,
) -> str:
    """Nettoie et valide une chaîne de caractères."""

    if value is None:
        if allow_empty:
            return ""

        raise ValueError(f"{field_name} ne peut pas être vide.")

    text = str(value).strip()

    if not text and not allow_empty:
        raise ValueError(f"{field_name} ne peut pas être vide.")

    if len(text) > max_length:
        raise ValueError(
            f"{field_name} dépasse la longueur maximale "
            f"de {max_length} caractères."
        )

    return text


def _safe_float(
    value: Any,
    default: Optional[float] = None,
) -> float:
    """Convertit une valeur en nombre flottant fini."""

    try:
        result = float(value)

        if not math.isfinite(result):
            raise ValueError("Valeur numérique non finie.")

        return result

    except (TypeError, ValueError, OverflowError):

        if default is not None:
            return float(default)

        raise ValueError("Valeur numérique invalide.")


def _clamp(
    value: Any,
    minimum: float,
    maximum: float,
    default: Optional[float] = None,
) -> float:
    """Limite une valeur à un intervalle."""

    number = _safe_float(value, default)

    return max(minimum, min(maximum, number))


def _safe_limit(value: Any) -> int:
    """Valide la limite de résultats demandée pour un audit."""

    try:
        limit = int(value)

    except (TypeError, ValueError, OverflowError):
        limit = DEFAULT_AUDIT_LIMIT

    return max(1, min(MAX_AUDIT_LIMIT, limit))


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convertit une ligne SQLite en dictionnaire."""

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return dict(row)

    return {}


def _normalize_thought_type(value: Any) -> str:
    """Normalise le type de raisonnement."""

    thought_type = _clean_text(
        value,
        "thought_type",
        max_length=100,
    ).lower()

    # Les types personnalisés restent autorisés.
    # Cela évite de bloquer les futurs modules cognitifs.
    return thought_type


# ============================================================
# INITIALISATION DES TABLES
# ============================================================

def init_cognition_tables(db: sqlite3.Connection) -> None:
    """Initialise les tables de raisonnement et de métacognition."""

    db.executescript("""
    CREATE TABLE IF NOT EXISTS cognitive_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id TEXT NOT NULL,

        thought_type TEXT NOT NULL,

        context_summary TEXT NOT NULL,

        decision_made TEXT NOT NULL,

        confidence REAL NOT NULL
            CHECK(confidence >= 0.0 AND confidence <= 1.0),

        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS metacognition_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id TEXT NOT NULL,

        reflection TEXT NOT NULL,

        adjustment_made TEXT NOT NULL,

        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_cognitive_traces_user
        ON cognitive_traces(user_id);

    CREATE INDEX IF NOT EXISTS idx_cognitive_traces_user_date
        ON cognitive_traces(user_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_metacognition_logs_user
        ON metacognition_logs(user_id);

    CREATE INDEX IF NOT EXISTS idx_metacognition_logs_user_date
        ON metacognition_logs(user_id, created_at);
    """)

    db.commit()


# ============================================================
# ENREGISTREMENT DES TRACES COGNITIVES
# ============================================================

def log_cognitive_trace(
    db: sqlite3.Connection,
    user_id: str,
    thought_type: str,
    context_summary: str,
    decision_made: str,
    confidence: float,
) -> dict[str, Any]:
    """Enregistre une trace de raisonnement.

    Une trace peut représenter :
    - Une observation.
    - Une analyse.
    - Une hypothèse.
    - Une décision.
    - Une prédiction.
    - Une réflexion.
    - Une correction.

    Les traces historiques ne sont jamais réécrites par l'audit.
    """

    user_id = _clean_text(
        user_id,
        "user_id",
        max_length=255,
    )

    thought_type = _normalize_thought_type(thought_type)

    context_summary = _clean_text(
        context_summary,
        "context_summary",
        max_length=20000,
        allow_empty=True,
    )

    decision_made = _clean_text(
        decision_made,
        "decision_made",
        max_length=20000,
    )

    confidence = _clamp(
        confidence,
        0.0,
        1.0,
    )

    now = utc_now()

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
            now,
        ),
    )

    trace_id = cursor.lastrowid

    db.commit()

    return {
        "id": trace_id,
        "user_id": user_id,
        "thought_type": thought_type,
        "context_summary": context_summary,
        "decision_made": decision_made,
        "confidence": confidence,
        "recorded_at": now,
    }


# ============================================================
# ÉVALUATION DU DOUTE
# ============================================================

def evaluate_decision_doubt(
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    """Évalue le niveau de doute associé à une décision.

    Trois comportements sont possibles :

    - ask_clarification :
      Chappie manque fortement d'informations.

    - proceed_with_caution :
      Chappie peut avancer, mais doit rester prudent.

    - proceed_confidently :
      Chappie peut poursuivre normalement.

    Cette fonction fournit une recommandation.
    Elle ne prend pas elle-même la décision finale.
    """

    confidence = _clamp(
        confidence,
        0.0,
        1.0,
    )

    threshold = _clamp(
        threshold,
        0.0,
        1.0,
        DEFAULT_CONFIDENCE_THRESHOLD,
    )

    is_uncertain = confidence < threshold

    if confidence < DEFAULT_DOUBT_THRESHOLD:

        action = "ask_clarification"

    elif is_uncertain:

        action = "proceed_with_caution"

    else:

        action = "proceed_confidently"

    if confidence < 0.25:
        doubt_level = "very_high"

    elif confidence < 0.40:
        doubt_level = "high"

    elif confidence < 0.60:
        doubt_level = "moderate"

    elif confidence < 0.85:
        doubt_level = "low"

    else:
        doubt_level = "very_low"

    return {
        "confidence": round(confidence, 4),
        "threshold": round(threshold, 4),
        "is_uncertain": is_uncertain,
        "doubt_level": doubt_level,
        "recommended_action": action,
    }


# ============================================================
# RÉCUPÉRATION DES TRACES
# ============================================================

def get_cognitive_traces(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> list[dict[str, Any]]:
    """Récupère les dernières traces cognitives d'un utilisateur."""

    user_id = _clean_text(
        user_id,
        "user_id",
        max_length=255,
    )

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
        (user_id, limit),
    ).fetchall()

    result = []

    for row in rows:

        if isinstance(row, sqlite3.Row):
            result.append(dict(row))

        elif isinstance(row, dict):
            result.append(dict(row))

        else:
            result.append({
                "id": row[0],
                "user_id": row[1],
                "thought_type": row[2],
                "context_summary": row[3],
                "decision_made": row[4],
                "confidence": row[5],
                "created_at": row[6],
            })

    return result


# ============================================================
# HISTORIQUE MÉTACOGNITIF
# ============================================================

def get_metacognition_logs(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> list[dict[str, Any]]:
    """Récupère les derniers audits métacognitifs."""

    user_id = _clean_text(
        user_id,
        "user_id",
        max_length=255,
    )

    limit = _safe_limit(limit)

    rows = db.execute(
        """
        SELECT
            id,
            user_id,
            reflection,
            adjustment_made,
            created_at

        FROM metacognition_logs

        WHERE user_id = ?

        ORDER BY id DESC

        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    result = []

    for row in rows:

        if isinstance(row, sqlite3.Row):
            result.append(dict(row))

        elif isinstance(row, dict):
            result.append(dict(row))

        else:
            result.append({
                "id": row[0],
                "user_id": row[1],
                "reflection": row[2],
                "adjustment_made": row[3],
                "created_at": row[4],
            })

    return result


# ============================================================
# AUDIT MÉTACOGNITIF
# ============================================================

def run_metacognitive_audit(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> dict[str, Any]:
    """Analyse les dernières traces cognitives.

    L'audit cherche à identifier :

    - Le niveau moyen de confiance.
    - Les variations de confiance.
    - Les raisonnements les plus fréquents.
    - Les domaines dans lesquels Chappie doute.
    - Une attitude recommandée pour la suite.

    L'audit n'altère jamais les traces historiques.

    Attention :
    Une confiance élevée ne signifie pas nécessairement
    qu'une décision est correcte.
    """

    user_id = _clean_text(
        user_id,
        "user_id",
        max_length=255,
    )

    limit = _safe_limit(limit)

    traces = get_cognitive_traces(
        db,
        user_id,
        limit,
    )

    if not traces:

        return {
            "user_id": user_id,
            "trace_count": 0,
            "average_confidence": None,
            "reflection": "Pas assez de données pour réaliser un audit métacognitif.",
            "adjustment_made": "aucun",
            "trend": "unknown",
            "created_at": utc_now(),
        }

    confidences = [
        _clamp(
            trace.get("confidence", 0.0),
            0.0,
            1.0,
        )
        for trace in traces
    ]

    avg_confidence = sum(confidences) / len(confidences)

    # Les traces sont récupérées de la plus récente à la plus ancienne.
    # On compare donc les premières aux dernières pour détecter une tendance.
    if len(confidences) >= 4:

        half = max(1, len(confidences) // 2)

        recent_average = sum(confidences[:half]) / len(confidences[:half])

        older_average = sum(confidences[half:]) / len(confidences[half:])

        difference = recent_average - older_average

        if difference >= 0.10:
            trend = "improving"

        elif difference <= -0.10:
            trend = "declining"

        else:
            trend = "stable"

    else:

        recent_average = avg_confidence
        older_average = avg_confidence
        trend = "insufficient_data"

    # Analyse des types de raisonnements.
    thought_counts: dict[str, int] = {}

    for trace in traces:

        thought_type = str(
            trace.get("thought_type", "unknown")
        )

        thought_counts[thought_type] = (
            thought_counts.get(thought_type, 0) + 1
        )

    most_common_thoughts = sorted(
        thought_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    # Analyse des niveaux de confiance.
    if avg_confidence < 0.40:

        reflection = (
            f"Doute important détecté sur les {len(traces)} "
            f"dernières réflexions. "
            f"Confiance moyenne : {avg_confidence:.2f}."
        )

        adjustment = (
            "Renforcer la prudence, rechercher les informations manquantes "
            "et demander confirmation avant les affirmations importantes."
        )

    elif avg_confidence < 0.60:

        reflection = (
            f"Confiance relativement faible sur les {len(traces)} "
            f"dernières réflexions. "
            f"Confiance moyenne : {avg_confidence:.2f}."
        )

        adjustment = (
            "Vérifier davantage les hypothèses et distinguer "
            "les faits des interprétations."
        )

    elif avg_confidence > 0.90:

        reflection = (
            f"Confiance très élevée sur les {len(traces)} "
            f"dernières réflexions. "
            f"Confiance moyenne : {avg_confidence:.2f}."
        )

        adjustment = (
            "Conserver l'initiative tout en vérifiant les raisonnements "
            "importants pour éviter un excès de confiance."
        )

    elif avg_confidence > 0.85:

        reflection = (
            f"Bonne assurance sur les raisonnements récents. "
            f"Confiance moyenne : {avg_confidence:.2f}."
        )

        adjustment = (
            "Poursuivre les initiatives lorsque les informations "
            "sont suffisamment fiables."
        )

    else:

        reflection = (
            f"Niveau de certitude équilibré. "
            f"Confiance moyenne : {avg_confidence:.2f}."
        )

        adjustment = (
            "Conserver la posture actuelle et continuer "
            "à évaluer les incertitudes."
        )

    if trend == "improving":

        reflection += (
            " La confiance progresse dans les traces les plus récentes."
        )

    elif trend == "declining":

        reflection += (
            " Une diminution de confiance est observée dans les traces récentes."
        )

    elif trend == "stable":

        reflection += (
            " Le niveau de confiance reste relativement stable."
        )

    now = utc_now()

    db.execute(
        """
        INSERT INTO metacognition_logs (
            user_id,
            reflection,
            adjustment_made,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            reflection,
            adjustment,
            now,
        ),
    )

    db.commit()

    return {
        "user_id": user_id,
        "trace_count": len(traces),
        "average_confidence": round(avg_confidence, 4),
        "recent_average_confidence": round(recent_average, 4),
        "older_average_confidence": round(older_average, 4),
        "trend": trend,
        "thought_types": thought_counts,
        "most_common_thoughts": [
            {
                "thought_type": thought_type,
                "count": count,
            }
            for thought_type, count in most_common_thoughts
        ],
        "reflection": reflection,
        "adjustment_made": adjustment,
        "created_at": now,
    }


# ============================================================
# STATISTIQUES COGNITIVES
# ============================================================

def get_cognition_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    """Retourne des statistiques générales sur la cognition."""

    user_id = _clean_text(
        user_id,
        "user_id",
        max_length=255,
    )

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
        (user_id,),
    ).fetchone()

    audit_row = db.execute(
        """
        SELECT COUNT(*)
        FROM metacognition_logs
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if isinstance(trace_row, sqlite3.Row):
        trace_stats = dict(trace_row)

    else:
        trace_stats = {
            "total_traces": trace_row[0],
            "average_confidence": trace_row[1],
            "minimum_confidence": trace_row[2],
            "maximum_confidence": trace_row[3],
        }

    return {
        "user_id": user_id,
        "total_traces": int(trace_stats["total_traces"] or 0),
        "average_confidence": (
            round(float(trace_stats["average_confidence"]), 4)
            if trace_stats["average_confidence"] is not None
            else None
        ),
        "minimum_confidence": trace_stats["minimum_confidence"],
        "maximum_confidence": trace_stats["maximum_confidence"],
        "total_metacognitive_audits": int(audit_row[0] or 0),
    }
