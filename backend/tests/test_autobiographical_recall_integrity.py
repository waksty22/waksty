"""Corruption resistance for autobiographical recall."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    init_autobiographical_tables,
    search_autobiographical_events,
    find_related_autobiographical_events,
)


def test_autobiographical_recall_skips_malformed_persisted_candidates():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)
    db.execute(
        """INSERT INTO autobiographical_events
           (user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES ('creator', 1, 'user', 'user_statement',
                   'Horloge mécanique dans le salon',
                   '2026-11-26T10:00:00Z', 3, '2026-11-26T10:00:00Z')"""
    )
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute(
        """INSERT INTO autobiographical_events
           (user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES ('creator', 2, 'user', 'user_statement', ?,
                   '2026-11-27T10:00:00Z', 3, '2026-11-27T10:00:00Z')""",
        (sqlite3.Binary(b"broken-content"),),
    )
    db.execute(
        """INSERT INTO autobiographical_events
           (user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES ('creator', 3, 'user', 'user_statement',
                   'Horloge mécanique corrompue',
                   '2026-11-27T11:00:00Z', ?, '2026-11-27T11:00:00Z')""",
        (sqlite3.Binary(b"broken-importance"),),
    )
    db.commit()

    recalled = search_autobiographical_events(
        db, "creator", "horloge mécanique", limit=5
    )
    assert [item["id"] for item in recalled] == [1]
    assert find_related_autobiographical_events(
        db, "creator", event_id=1, limit=5
    ) == []
    assert find_related_autobiographical_events(
        db, "creator", event_id=3, limit=5
    ) == []
    db.close()
