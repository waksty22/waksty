"""Module de cognition, de boucle de décision et de métacognition pour Chappie."""
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
