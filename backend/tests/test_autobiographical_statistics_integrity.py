"""Statistics must exclude malformed episodes rejected by autobiographical recall."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    autobiographical_statistics,
    init_autobiographical_tables,
)


def test_autobiographical_statistics_count_only_recall_eligible_events_and_links():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)

    timestamp = "2026-11-27T10:00:00Z"
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("creator", 1, "user", "user_statement", "J'ai un vélo rouge",
             timestamp, 3, timestamp),
            ("creator", 2, "assistant", "chappie_response", "Je m'en souviendrai",
             timestamp, 1, timestamp),
        ],
    )

    # Simulate damaged legacy rows that SQLite's normal CHECK constraints
    # would reject. Recall already excludes these; statistics must agree.
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', 3, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        (sqlite3.Binary(b"broken-content"), timestamp, timestamp),
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', 4, 'user', 'user_statement',
                'Date invalide', 'not-a-date', 3, ?)
        """,
        (timestamp,),
    )
    db.executemany(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', ?, ?, 'same_dialogue_turn', ?)
        """,
        [(1, 2, timestamp), (1, 3, timestamp)],
    )
    db.commit()

    assert autobiographical_statistics(db, "creator") == {
        "total_events": 2,
        "user_events": 1,
        "chappie_events": 1,
        "dialogue_links": 1,
    }
    # Other users' episodes must never leak into this user's counters.
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('another-user', 5, 'user', 'user_statement',
                'Un autre souvenir', ?, 3, ?)
        """,
        (timestamp, timestamp),
    )
    assert autobiographical_statistics(db, "creator")["total_events"] == 2
    db.close()
