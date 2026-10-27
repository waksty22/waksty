"""Module de cognition, de boucle de décision et de métacognition pour Chappie.
Gère les traces de raisonnement, l'évaluation du doute et l'auto-critique.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_cognition_tables(db: sqlite3.Connection) -> None:
    """Initialise les tables pour la trace de raisonnement et l'évaluation métacognitive."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS cognitive_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        thought_type TEXT NOT NULL,
        context_summary TEXT NOT NULL,
        decision_made TEXT NOT NULL,
        confidence REAL NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS metacognition_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        reflection TEXT NOT NULL,
        adjustment_made TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    db.commit()


def log_cognitive_trace(
    db: sqlite3.Connection,
    user_id: str,
    thought_type: str,
    context_summary: str,
    decision_made: str,
    confidence: float
) -> dict[str, Any]:
    """Enregistre une trace de raisonnement (décision, analyse, hypothèse)."""
    now = utc_now()
    confidence = max(0.0, min(1.0, float(confidence)))

    db.execute("""
        INSERT INTO cognitive_traces (user_id, thought_type, context_summary, decision_made, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, thought_type.strip(), context_summary.strip(), decision_made.strip(), confidence, now))
    db.commit()

    return {
        "thought_type": thought_type,
        "decision_made": decision_made,
        "confidence": confidence,
        "recorded_at": now
    }


def evaluate_decision_doubt(confidence: float, threshold: float = 0.6) -> dict[str, Any]:
    """Évalue si Chappie est en situation de doute cognitive.
    Permet à Chappie de ralentir son raisonnement s'il n'est pas sûr de lui.
    """
    confidence = max(0.0, min(1.0, float(confidence)))
    is_uncertain = confidence < threshold

    if is_uncertain:
        action = "ask_clarification" if confidence < 0.4 else "proceed_with_caution"
    else:
        action = "proceed_confidently"

    return {
        "confidence": confidence,
        "is_uncertain": is_uncertain,
        "recommended_action": action
    }


def run_metacognitive_audit(db: sqlite3.Connection, user_id: str, limit: int = 10) -> dict[str, Any]:
    """Analyse les dernières traces de raisonnement pour en tirer une réflexion métacognitive
    et adapter son attitude sans altérer son historique ou son évolution.
    """
    rows = db.execute("""
        SELECT thought_type, decision_made, confidence, created_at
        FROM cognitive_traces
        WHERE user_id = ?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit)).fetchall()

    if not rows:
        return {"reflection": "Pas assez de données pour l'audit.", "adjustment": "aucun"}

    traces = [dict(r) for r in rows]
    avg_confidence = sum(t["confidence"] for t in traces) / len(traces)

    if avg_confidence < 0.5:
        reflection = f"Doute fréquent détecté sur les {len(traces)} dernières réflexions (Confiance moy. : {avg_confidence:.2f})."
        adjustment = "Augmenter la prudence et demander confirmation avant d'affirmer des faits."
    elif avg_confidence > 0.85:
        reflection = f"Excellente assurance sur les raisonnements récents (Confiance moy. : {avg_confidence:.2f})."
        adjustment = "Prendre davantage d'initiatives autonomes."
    else:
        reflection = f"Niveau de certitude équilibré (Confiance moy. : {avg_confidence:.2f})."
        adjustment = "Conserver la posture actuelle."

    now = utc_now()
    db.execute("""
        INSERT INTO metacognition_logs (user_id, reflection, adjustment_made, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, reflection, adjustment, now))
    db.commit()

    return {
        "user_id": user_id,
        "average_confidence": round(avg_confidence, 2),
        "reflection": reflection,
        "adjustment_made": adjustment,
        "created_at": now
    }
