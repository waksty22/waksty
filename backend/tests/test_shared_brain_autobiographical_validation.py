"""Shared Chat/Live snapshots must exclude malformed autobiographical rows."""
from __future__ import annotations

import sqlite3

from cognition.shared_brain import _rows


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE autobiographical_events (
            id INTEGER, user_id TEXT, source_conversation_id INTEGER,
            actor TEXT, event_type TEXT, content TEXT, happened_at TEXT,
            importance INTEGER
        )"""
    )
    db.executemany(
        """INSERT INTO autobiographical_events
           (id, user_id, source_conversation_id, actor, event_type,
            content, happened_at, importance)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "creator", 1, "user", "user_statement", "Horloge rouge dans le salon", "2026-11-27T10:00:00Z", 3),
            (2, "creator", 2, "user", "user_statement", sqlite3.Binary(b"broken content"), "2026-11-27T11:00:00Z", 3),
            (3, "creator", 3, "system", "user_statement", "Horloge système", "2026-11-27T12:00:00Z", 3),
            (4, "creator", 4, "user", "user_statement", "Horloge date invalide", "not-a-date", 3),
            (5, "creator", 5, "user", "user_statement", "Horloge importance invalide", "2026-11-27T13:00:00Z", sqlite3.Binary(b"bad")),
            (6, "other-user", 6, "user", "user_statement", "Horloge privée", "2026-11-27T14:00:00Z", 3),
        ],
    )
    return db


def test_shared_brain_autobiographical_rows_filter_corruption_without_query():
    db = _database()
    rows = _rows(
        db, "autobiographical_events", "id DESC", "creator", 20
    )
    assert [row["id"] for row in rows] == [1]
    db.close()


def test_shared_brain_autobiographical_query_filters_corruption_before_limit():
    db = _database()
    rows = _rows(
        db, "autobiographical_events", "id DESC", "creator", 1,
        query="horloge rouge",
    )
    assert [row["id"] for row in rows] == [1]
    assert all(row["user_id"] == "creator" for row in rows)
    db.close()
