"""Durable outbox for post-commit conversation finalization.

Conversation rows and their pending finalization marker are committed in the
same database transaction. A later process can safely retry consolidation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_conversation_finalization_outbox(db: Any) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS conversation_finalization_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            through_conversation_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'completed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_attempt_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            UNIQUE(user_id, through_conversation_id)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_finalization_pending
        ON conversation_finalization_outbox(status, id)
    """)


def enqueue_conversation_finalization(
    db: Any, user_id: str, through_conversation_id: int,
) -> bool:
    user = str(user_id or "").strip()[:128]
    through_id = int(through_conversation_id)
    if not user or through_id < 1:
        raise ValueError("A valid user and conversation cursor are required")
    init_conversation_finalization_outbox(db)
    cursor = db.execute("""
        INSERT OR IGNORE INTO conversation_finalization_outbox
            (user_id, through_conversation_id, status, attempts, created_at)
        VALUES (?, ?, 'pending', 0, ?)
    """, (user, through_id, _now()))
    return cursor.rowcount == 1


def list_pending_conversation_finalizations(
    db: Any, limit: int = 100, user_id: str | None = None,
) -> list[dict[str, Any]]:
    init_conversation_finalization_outbox(db)
    where = "status='pending'"
    params: list[Any] = []
    if user_id is not None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("A valid user filter is required")
        where += " AND user_id=?"
        params.append(user_id.strip())
    params.append(max(1, min(int(limit), 500)))
    rows = db.execute(f"""
        SELECT id, user_id, through_conversation_id, attempts
        FROM conversation_finalization_outbox
        WHERE {where}
        ORDER BY id ASC
        LIMIT ?
    """, params).fetchall()
    return [
        {
            "id": int(row["id"]),
            "user_id": str(row["user_id"]),
            "through_conversation_id": int(row["through_conversation_id"]),
            "attempts": int(row["attempts"]),
        }
        for row in rows
    ]


def mark_conversation_finalization(
    db: Any, job_id: int, error: str | None = None,
) -> None:
    now = _now()
    if error is not None:
        db.execute("""
            UPDATE conversation_finalization_outbox
            SET attempts=attempts+1, last_error=?, last_attempt_at=?
            WHERE id=? AND status='pending'
        """, (str(error)[:1000], now, int(job_id)))
    else:
        db.execute("""
            UPDATE conversation_finalization_outbox
            SET attempts=attempts+1, last_error='', last_attempt_at=?,
                status='completed', completed_at=?
            WHERE id=? AND status='pending'
        """, (now, now, int(job_id)))
