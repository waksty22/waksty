"""Module de gestion du curriculum cognitif et de l'apprentissage progressif de Chappie.
Gère les tests de compétences et le suivi des jalons de développement (milestones) basés sur la réussite réelle.
"""

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
            achieved_at TEXT,
            UNIQUE(user_id, stage_name)
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
    
    # Initialisation des paliers par défaut pour chaque utilisateur s'ils n'existent pas
    default_stages = [
        ("Nouveau-né (Éveil)", 1.0),
        ("Enfant (Apprenti)", 3.0),
        ("Adolescent (Explorateur)", 5.0),
        ("Adulte (Complice)", 8.0)
    ]
    
    users = db.execute("SELECT DISTINCT user_id FROM skills").fetchall()
    for row in users:
        uid = row["user_id"]
        for stage_name, min_mat in default_stages:
            db.execute("""
                INSERT OR IGNORE INTO cognitive_milestones (user_id, stage_name, min_maturity, status)
                VALUES (?, ?, ?, ?)
            """, (uid, stage_name, min_mat, "achieved" if min_mat == 1.0 else "locked"))
            
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


def update_cognitive_milestones(db: sqlite3.Connection, user_id: str, current_maturity: float) -> list[dict[str, Any]]:
    """
    Met à jour le statut des jalons de développement de Chappie en combinant 
    la maturité cognitive globale ET la réussite effective aux tests de compétences.
    """
    now = utc_now()
    
    # Récupère le taux de réussite moyen aux tests de l'utilisateur
    test_stats = db.execute("""
        SELECT COUNT(*) as total_tests, COALESCE(AVG(passed), 0.0) as success_rate 
        FROM competency_tests WHERE user_id = ?
    """, (user_id,)).fetchone()
    
    total_tests = test_stats["total_tests"] if test_stats else 0
    success_rate = test_stats["success_rate"] if test_stats else 0.0

    milestones = db.execute("""
        SELECT id, stage_name, min_maturity, status FROM cognitive_milestones WHERE user_id = ?
    """, (user_id,)).fetchall()
    
    updated_milestones = []
    for m in milestones:
        m_id = m["id"]
        min_mat = m["min_maturity"]
        status = m["status"]
        
        new_status = status
        achieved_at = None
        
        # Règle active : Le premier palier (Nouveau-né) est acquis d'office. 
        # Pour les suivants, il faut la maturité ET au moins un test validé (ou seuil de tests).
        can_achieve = False
        if min_mat <= 1.0:
            can_achieve = True
        elif current_maturity >= min_mat and total_tests > 0 and success_rate >= 0.5:
            can_achieve = True

        if can_achieve and status == "locked":
            new_status = "achieved"
            achieved_at = now
            db.execute("""
                UPDATE cognitive_milestones SET status = ?, achieved_at = ? WHERE id = ?
            """, (new_status, achieved_at, m_id))

        updated_milestones.append({
            "stage_name": m["stage_name"],
            "min_maturity": min_mat,
            "status": new_status
        })
        
    db.commit()
    return updated_milestones
