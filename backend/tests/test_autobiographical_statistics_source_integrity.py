"""Statistics must exclude autobiographical rows with broken source provenance."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import autobiographical_statistics, init_autobiographical_tables


def test_statistics_exclude_events_whose_source_message_does_not_match():
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
    timestamp = "2026-11-27T10:00:00Z"
    db.executemany(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
        [
            (1, "creator", "user", "Souvenir correctement ancré", timestamp),
            (2, "creator", "user", "Texte source différent", timestamp),
            (3, "other-user", "user", "Souvenir privé", timestamp),
        ],
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES (?, ?, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        [
            ("creator", 1, "Souvenir correctement ancré", timestamp, timestamp),
            ("creator", 2, "Souvenir copié incohérent", timestamp, timestamp),
            ("creator", 3, "Souvenir d'un autre utilisateur", timestamp, timestamp),
        ],
    )
    db.execute(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', 1, 2, 'same_dialogue_turn', ?)
        """,
        (timestamp,),
    )
    db.commit()

    assert autobiographical_statistics(db, "creator") == {
        "total_events": 1,
        "user_events": 1,
        "chappie_events": 0,
        "dialogue_links": 0,
    }
    db.close()
