"""Supervised imitation and developmental practice records for Chappie.

This module records demonstrations and externally performed practice. It never
executes a physical or digital action. Validation requires explicit supervisor
approval and documented practice evidence.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

MAX_BEHAVIOR = 1200
MAX_CONTEXT = 1200
MAX_EVIDENCE = 2000
ALLOWED_SOURCES = {"demonstrated", "explicitly_taught"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} doit être du texte.")
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(f"{field} est vide ou dépasse {limit} caractères.")
    return value


def init_supervised_learning_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS imitation_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            behavior TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL
                CHECK(source_type IN ('demonstrated','explicitly_taught')),
            evidence TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'observed'
                CHECK(status IN ('observed','practiced','validated','rejected')),
            supervisor_approved INTEGER NOT NULL DEFAULT 0
                CHECK(supervisor_approved IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_imitation_user_status
            ON imitation_examples(user_id, status, id DESC);

        CREATE TABLE IF NOT EXISTS imitation_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            example_id INTEGER NOT NULL
                REFERENCES imitation_examples(id) ON DELETE CASCADE,
            result TEXT NOT NULL,
            evidence TEXT NOT NULL,
            successful INTEGER NOT NULL CHECK(successful IN (0,1)),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_imitation_attempts_user
            ON imitation_attempts(user_id, example_id, id DESC);
    """)


def record_demonstration(
    db: sqlite3.Connection,
    user_id: str,
    behavior: str,
    evidence: str,
    source_type: str = "demonstrated",
    context: str = "",
) -> dict[str, Any]:
    behavior = _required_text(behavior, "Comportement", MAX_BEHAVIOR)
    evidence = _required_text(evidence, "Preuve de démonstration", MAX_EVIDENCE)
    context = str(context or "").strip()
    if len(context) > MAX_CONTEXT:
        raise ValueError("Le contexte est trop long.")
    if source_type not in ALLOWED_SOURCES:
        raise ValueError("Source attendue : demonstrated ou explicitly_taught.")
    now = _now()
    cur = db.execute(
        """INSERT INTO imitation_examples
           (user_id,behavior,context,source_type,evidence,status,
            supervisor_approved,created_at,updated_at)
           VALUES (?,?,?,?,?,'observed',0,?,?)""",
        (user_id, behavior, context, source_type, evidence, now, now),
    )
    db.commit()
    return {
        "id": cur.lastrowid, "behavior": behavior, "context": context,
        "source_type": source_type, "evidence": evidence,
        "status": "observed", "supervisor_approved": False,
        "created_at": now,
    }


def record_practice(
    db: sqlite3.Connection,
    user_id: str,
    example_id: int,
    result: str,
    evidence: str,
    successful: bool,
) -> dict[str, Any]:
    row = db.execute(
        "SELECT id,status FROM imitation_examples WHERE id=? AND user_id=?",
        (example_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Démonstration introuvable pour cet utilisateur.")
    if row["status"] in {"validated", "rejected"}:
        raise ValueError("Cette démonstration est déjà clôturée.")
    result = _required_text(result, "Résultat de la pratique", MAX_EVIDENCE)
    evidence = _required_text(evidence, "Preuve de pratique", MAX_EVIDENCE)
    if not isinstance(successful, bool):
        raise ValueError("successful doit être un booléen.")
    now = _now()
    cur = db.execute(
        """INSERT INTO imitation_attempts
           (user_id,example_id,result,evidence,successful,created_at)
           VALUES (?,?,?,?,?,?)""",
        (user_id, example_id, result, evidence, int(successful), now),
    )
    db.execute(
        """UPDATE imitation_examples SET status='practiced',updated_at=?
           WHERE id=? AND user_id=?""",
        (now, example_id, user_id),
    )
    db.commit()
    return {
        "attempt_id": cur.lastrowid, "example_id": example_id,
        "result": result, "evidence": evidence,
        "successful": successful, "status": "practiced",
    }


def validate_imitation(
    db: sqlite3.Connection,
    user_id: str,
    example_id: int,
    supervisor_approved: bool,
    validation_evidence: str,
) -> dict[str, Any]:
    if supervisor_approved is not True:
        raise ValueError("Une validation explicite du superviseur est obligatoire.")
    validation_evidence = _required_text(
        validation_evidence, "Preuve de validation", MAX_EVIDENCE
    )
    row = db.execute(
        """SELECT id,status FROM imitation_examples
           WHERE id=? AND user_id=?""",
        (example_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Démonstration introuvable pour cet utilisateur.")
    if row["status"] != "practiced":
        raise ValueError("Chappie doit d'abord avoir documenté au moins une pratique.")
    attempts = db.execute(
        """SELECT COUNT(*) FROM imitation_attempts
           WHERE example_id=? AND user_id=? AND successful=1""",
        (example_id, user_id),
    ).fetchone()[0]
    if not attempts:
        raise ValueError("Aucune pratique réussie documentée.")
    now = _now()
    db.execute(
        """UPDATE imitation_examples
           SET status='validated',supervisor_approved=1,
               evidence=evidence || char(10) || 'Validation : ' || ?,
               updated_at=?
           WHERE id=? AND user_id=?""",
        (validation_evidence, now, example_id, user_id),
    )
    db.commit()
    return {
        "example_id": example_id, "status": "validated",
        "supervisor_approved": True,
        "successful_attempts": attempts, "updated_at": now,
    }


def reject_imitation(
    db: sqlite3.Connection,
    user_id: str,
    example_id: int,
    reason: str,
) -> dict[str, Any]:
    reason = _required_text(reason, "Motif du rejet", MAX_EVIDENCE)
    row = db.execute(
        "SELECT status FROM imitation_examples WHERE id=? AND user_id=?",
        (example_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Démonstration introuvable pour cet utilisateur.")
    if row["status"] == "validated":
        raise ValueError("Une imitation validée ne peut pas être rejetée directement.")
    now = _now()
    db.execute(
        """UPDATE imitation_examples SET status='rejected',
           evidence=evidence || char(10) || 'Rejet : ' || ?,
           updated_at=? WHERE id=? AND user_id=?""",
        (reason, now, example_id, user_id),
    )
    db.commit()
    return {"example_id": example_id, "status": "rejected", "reason": reason}


def list_imitation_learning(
    db: sqlite3.Connection, user_id: str, limit: int = 50
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    examples = db.execute(
        """SELECT id,behavior,context,source_type,evidence,status,
                  supervisor_approved,created_at,updated_at
           FROM imitation_examples WHERE user_id=?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    result = []
    for row in examples:
        item = dict(row)
        attempts = db.execute(
            """SELECT id,result,evidence,successful,created_at
               FROM imitation_attempts
               WHERE user_id=? AND example_id=? ORDER BY id DESC LIMIT 10""",
            (user_id, item["id"]),
        ).fetchall()
        item["attempts"] = [dict(a) for a in attempts]
        result.append(item)
    counts = db.execute(
        """SELECT status,COUNT(*) AS count FROM imitation_examples
           WHERE user_id=? GROUP BY status""",
        (user_id,),
    ).fetchall()
    return {
        "examples": result,
        "statistics": {row["status"]: row["count"] for row in counts},
        "total": sum(row["count"] for row in counts),
        "important_rule": (
            "Une observation ou une pratique ne prouve pas une maîtrise. "
            "Seule une validation explicite après une pratique réussie "
            "marque l'imitation comme acquise."
        ),
    }
