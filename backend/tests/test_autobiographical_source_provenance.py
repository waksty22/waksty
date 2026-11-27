"""Autobiographical episodes must remain grounded in their original same-user source."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    find_related_autobiographical_events,
    init_autobiographical_tables,
    list_autobiographical_events,
    search_autobiographical_events,
)


def test_recall_rejects_events_with_mismatched_or_foreign_source_messages():
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
            (1, "creator", "user", "Souvenir rouge dans le salon", timestamp),
            (2, "another-user", "user", "Souvenir rouge privé", timestamp),
            (3, "creator", "user", "Texte source différent", timestamp),
        ],
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        [
            (1, "Souvenir rouge dans le salon", timestamp, timestamp),
            (2, "Souvenir rouge privé", timestamp, timestamp),
            (3, "Souvenir rouge inventé", timestamp, timestamp),
        ],
    )
    db.commit()

    results = search_autobiographical_events(db, "creator", "souvenir rouge", limit=10)
    assert [item["source_conversation_id"] for item in results] == [1]
    listed = list_autobiographical_events(db, "creator", limit=10)
    assert [item["source_conversation_id"] for item in listed] == [1]
    assert find_related_autobiographical_events(
        db, "creator", event_id=1, limit=10
    ) == []
    db.close()


def test_linked_reply_is_not_returned_when_its_source_no_longer_matches():
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
        "INSERT INTO conversations VALUES (?, 'creator', ?, ?, ?)",
        [
            (1, "user", "Horloge rouge dans le salon", timestamp),
            (2, "assistant", "Réponse source modifiée", timestamp),
        ],
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "user", "user_statement", "Horloge rouge dans le salon",
             timestamp, 3, timestamp),
            (2, "assistant", "chappie_response", "Ancienne réponse conservée",
             timestamp, 1, timestamp),
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

    results = search_autobiographical_events(db, "creator", "horloge rouge", limit=5)
    assert len(results) == 1
    assert results[0]["source_conversation_id"] == 1
    assert results[0]["dialogue_context"] is False
    db.close()
