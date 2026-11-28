"""Autobiographical episodes must remain grounded in their original same-user source."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    find_related_autobiographical_events,
    init_autobiographical_tables,
    list_autobiographical_events,
    search_autobiographical_events,
    autobiographical_statistics,
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


def test_search_batches_source_provenance_checks_per_history_page():
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
    for source_id in range(1, 9):
        content = f"Souvenir horloge numéro {source_id}"
        db.execute(
            "INSERT INTO conversations VALUES (?, 'creator', 'user', ?, ?)",
            (source_id, content, timestamp),
        )
        db.execute(
            """
            INSERT INTO autobiographical_events
                (user_id, source_conversation_id, actor, event_type, content,
                 happened_at, importance, created_at)
            VALUES ('creator', ?, 'user', 'user_statement', ?, ?, 3, ?)
            """,
            (source_id, content, timestamp, timestamp),
        )
    db.commit()

    source_selects = []
    db.set_trace_callback(
        lambda statement: source_selects.append(statement)
        if "FROM conversations" in statement
        and "id IN (" in statement
        else None
    )
    results = search_autobiographical_events(
        db, "creator", "souvenir horloge", limit=10
    )

    assert len(results) == 8
    assert len(source_selects) == 1
    db.close()


def test_related_event_search_batches_source_provenance_checks_per_page():
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
    for source_id in range(1, 9):
        content = (
            "Souvenir horloge rouge maison"
            if source_id == 1
            else f"Souvenir horloge rouge numéro {source_id}"
        )
        db.execute(
            "INSERT INTO conversations VALUES (?, 'creator', 'user', ?, ?)",
            (source_id, content, timestamp),
        )
        db.execute(
            """
            INSERT INTO autobiographical_events
                (user_id, source_conversation_id, actor, event_type, content,
                 happened_at, importance, created_at)
            VALUES ('creator', ?, 'user', 'user_statement', ?, ?, 3, ?)
            """,
            (source_id, content, timestamp, timestamp),
        )
    db.commit()

    grouped_source_selects = []
    db.set_trace_callback(
        lambda statement: grouped_source_selects.append(statement)
        if "FROM conversations" in statement and "id IN (" in statement
        else None
    )
    results = find_related_autobiographical_events(
        db, "creator", event_id=1, limit=10
    )

    assert len(results) == 7
    assert len(grouped_source_selects) == 1
    assert all(item["relation_status"] == "candidate_only" for item in results)
    db.close()



def test_sql_provenance_accepts_ascii_whitespace_removed_during_indexing():
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
    timestamp = "2026-11-28T08:00:00Z"
    db.execute(
        "INSERT INTO conversations VALUES (1, 'creator', 'user', ?, ?)",
        ("\tSouvenir horloge rouge\n", timestamp),
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', 1, 'user', 'user_statement',
                'Souvenir horloge rouge', ?, 3, ?)
        """,
        (timestamp, timestamp),
    )
    db.commit()

    listed = list_autobiographical_events(db, "creator", limit=10)
    searched = search_autobiographical_events(
        db, "creator", "souvenir horloge", limit=5
    )
    stats = autobiographical_statistics(db, "creator")

    assert [item["source_conversation_id"] for item in listed] == [1]
    assert [item["source_conversation_id"] for item in searched] == [1]
    assert stats["total_events"] == 1
    db.close()
