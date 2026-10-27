"""Module de gestion du curriculum cognitif et de l'apprentissage progressif de Chappie."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Renvoie la date actuelle au format ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def init_learning_tables(db: sqlite3.Connection) -> None:
    """Initialise les tables liées au curriculum et aux tests de compétences."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cognitive_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            min_maturity REAL NOT NULL,
            status TEXT NOT NULL
                CHECK(status IN ('locked', 'in_progress', 'achieved'))
                DEFAULT 'locked',
            achieved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS competency_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            test_name TEXT NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0,
            score REAL NOT NULL DEFAULT 0.0,
            details TEXT NOT NULL DEFAULT '{}',
            tested_at TEXT NOT NULL
        );
        """
    )
    db.commit()


def evaluate_competency_test(
    db: sqlite3.Connection,
    user_id: str,
    test_name: str,
    passed: bool,
    score: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enregistre le résultat d'un test de compétence de Chappie."""
    if not user_id or not user_id.strip():
        raise ValueError("user_id ne peut pas être vide.")

    if not test_name or not test_name.strip():
        raise ValueError("test_name ne peut pas être vide.")

    score = max(0.0, min(100.0, float(score)))
    now = utc_now()
    passed_int = 1 if passed else 0
    details_json = json.dumps(details or {}, ensure_ascii=False)

    db.execute(
        """
        INSERT INTO competency_tests (
            user_id, test_name, passed, score, details, tested_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id.strip(),
            test_name.strip(),
            passed_int,
            score,
            details_json,
            now,
        ),
    )
    db.commit()

    return {
        "test_name": test_name.strip(),
        "passed": bool(passed),
        "score": score,
        "tested_at": now,
    }



