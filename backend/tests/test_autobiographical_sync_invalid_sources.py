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
            (4, "user", "Horodatage impossible", "not-a-date"),
            (5, "user", "Mon souvenir valide", "2026-11-27T10:03:00Z"),
        ],
    )
    db.commit()

    result = sync_autobiographical_events(db, "creator", limit=1)

    assert result["inserted"] == 1
    assert result["total_events"] == 1
    row = db.execute(
        "SELECT source_conversation_id, content FROM autobiographical_events"
    ).fetchone()
    assert tuple(row) == (5, "Mon souvenir valide")
    assert sync_autobiographical_events(db, "creator", limit=1)["inserted"] == 0
    db.close()


def test_dialogue_link_detection_uses_previous_same_user_message_across_interleaving():
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
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
        [
            (1, "creator", "user", "Premier message sans réponse", "2026-11-27T10:00:00Z"),
            (2, "other-user", "user", "Message d'un autre utilisateur", "2026-11-27T10:00:01Z"),
            (3, "creator", "user", "Deuxième message utilisateur", "2026-11-27T10:00:02Z"),
            (4, "creator", "assistant", "Réponse au deuxième message", "2026-11-27T10:00:02Z"),
        ],
    )
    db.commit()

    result = sync_autobiographical_events(db, "creator")

    assert result["inserted"] == 3
    links = db.execute(
        "SELECT source_event_id, target_event_id "
        "FROM autobiographical_links WHERE user_id='creator'"
    ).fetchall()
    assert links == []
    db.close()


def test_targeted_sync_links_only_newly_indexed_dialogue_replies():
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
    conversations = [
        (1, "user", "Ancien message utilisateur", "2026-11-27T10:00:00Z"),
        (2, "assistant", "Ancienne réponse", "2026-11-27T10:00:00Z"),
        (3, "user", "Nouveau message utilisateur", "2026-11-27T10:01:00Z"),
        (4, "assistant", "Nouvelle réponse", "2026-11-27T10:01:00Z"),
    ]
    db.executemany(
        "INSERT INTO conversations VALUES (?, 'creator', ?, ?, ?)",
        conversations,
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                conversation_id,
                role,
                "user_statement" if role == "user" else "chappie_response",
                content,
                created_at,
                3 if role == "user" else 1,
                created_at,
            )
            for conversation_id, role, content, created_at in conversations
        ],
    )
    db.commit()

    sync_autobiographical_events(db, "creator", conversation_ids=[3, 4])
    links = db.execute(
        """
        SELECT u.source_conversation_id, a.source_conversation_id
        FROM autobiographical_links l
        JOIN autobiographical_events u ON u.id=l.source_event_id
        JOIN autobiographical_events a ON a.id=l.target_event_id
        WHERE l.user_id='creator'
        ORDER BY u.source_conversation_id
        """
    ).fetchall()
    assert [tuple(row) for row in links] == [(3, 4)]

    # A full historical backfill still discovers the older pair.
    sync_autobiographical_events(db, "creator")
    links = db.execute(
        """
        SELECT u.source_conversation_id, a.source_conversation_id
        FROM autobiographical_links l
        JOIN autobiographical_events u ON u.id=l.source_event_id
        JOIN autobiographical_events a ON a.id=l.target_event_id
        WHERE l.user_id='creator'
        ORDER BY u.source_conversation_id
        """
    ).fetchall()
    assert [tuple(row) for row in links] == [(1, 2), (3, 4)]
    db.close()
