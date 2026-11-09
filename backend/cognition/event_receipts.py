"""V50.37 — transactional receipts for idempotent cognitive side effects.

Call claim_cognitive_event() on the same database connection and transaction
as the side effect it protects. This module deliberately does not commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3


def init_cognitive_event_receipt_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS cognitive_event_receipts (
            user_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            effect_kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, event_id, effect_kind)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_cognitive_event_receipts_created
        ON cognitive_event_receipts(user_id, created_at DESC)
    """)


def claim_cognitive_event(
    db: sqlite3.Connection,
    user_id: str,
    event_id: str | None,
    effect_kind: str,
) -> bool:
    """Claim an event/effect pair once; return False for an already claimed pair.

    A missing/blank event_id preserves legacy behavior and does not create a
    receipt. The caller owns commit/rollback so receipt and side effect can be
    made atomic on this same connection.
    """
    clean_user = str(user_id or "").strip()[:128]
    clean_event = str(event_id or "").strip()[:160]
    clean_kind = str(effect_kind or "").strip()[:80]
    if not clean_user:
        raise ValueError("user_id is required")
    if not clean_kind:
        raise ValueError("effect_kind is required")
    if not clean_event:
        return True

    init_cognitive_event_receipt_table(db)
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO cognitive_event_receipts
            (user_id, event_id, effect_kind, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            clean_user,
            clean_event,
            clean_kind,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return cursor.rowcount == 1
