"""Invalid source rows must not starve autobiographical synchronization."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import init_autobiographical_tables, sync_autobiographical_events


def test_invalid_early_conversations_do_not_starve_valid_autobiographical_sync():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    init_autobiographical_tables(db)
    db.executemany(
        "INSERT INTO conversations VALUES (?, 'creator', ?, ?, ?)",
        [
            (1, "user", sqlite3.Binary(b"broken"), "2026-11-27T10:00:00Z"),
            (2, "user", "   ", "2026-11-27T10:01:00Z"),
            (3, "system", "Type non indexable", "2026-11-27T10:02:00Z"),
            (4, "user", "Mon souvenir valide", "2026-11-27T10:03:00Z"),
        ],
    )
    db.commit()

    result = sync_autobiographical_events(db, "creator", limit=1)

    assert result["inserted"] == 1
    assert result["total_events"] == 1
    row = db.execute(
        "SELECT source_conversation_id, content FROM autobiographical_events"
    ).fetchone()
    assert tuple(row) == (4, "Mon souvenir valide")
    assert sync_autobiographical_events(db, "creator", limit=1)["inserted"] == 0
    db.close()
