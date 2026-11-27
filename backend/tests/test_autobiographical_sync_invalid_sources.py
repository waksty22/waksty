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

    # Legacy rows with missing or mismatched sources must not inflate the
    # synchronization counters shown to the API/dashboard.
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', 999, 'user', 'user_statement',
                'Souvenir sans source', '2026-11-27T10:04:00Z', 3,
                '2026-11-27T10:04:00Z')
        """
    )
    invalid_event_id = db.execute(
        "SELECT id FROM autobiographical_events WHERE source_conversation_id=999"
    ).fetchone()[0]
    valid_event_id = db.execute(
        "SELECT id FROM autobiographical_events WHERE source_conversation_id=5"
    ).fetchone()[0]
    db.execute(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', ?, ?, 'same_dialogue_turn', '2026-11-27T10:04:00Z')
        """,
        (valid_event_id, invalid_event_id),
    )
    db.commit()

    counted = sync_autobiographical_events(db, "creator", limit=1)
    assert counted == {
        "inserted": 0,
        "total_events": 1,
        "dialogue_links": 0,
    }
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

    traced_sql: list[str] = []
    db.set_trace_callback(traced_sql.append)
    targeted_result = sync_autobiographical_events(
        db, "creator", conversation_ids=[3, 4], include_counts=False
    )
    db.set_trace_callback(None)
    assert targeted_result == {"inserted": 0}
    assert not any(
        "COUNT(*)" in statement.upper()
        and "AUTOBIOGRAPHICAL_" in statement.upper()
        for statement in traced_sql
    )
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

    # A full historical backfill still discovers the older pair and
    # retains the detailed statistics used by the API.
    full_result = sync_autobiographical_events(db, "creator")
    assert full_result["total_events"] == 4
    assert full_result["dialogue_links"] == 2
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



def test_targeted_sync_deduplicates_conversation_ids_before_sql_binding():
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
            (1, "user", "Nouveau message utilisateur", "2026-11-27T10:00:00Z"),
            (2, "assistant", "Réponse associée", "2026-11-27T10:00:00Z"),
        ],
    )
    db.commit()

    result = sync_autobiographical_events(
        db, "creator", conversation_ids=[1, 1, 2, 2], include_counts=False
    )

    assert result == {"inserted": 2}
    links = db.execute(
        """
        SELECT u.source_conversation_id, a.source_conversation_id
        FROM autobiographical_links l
        JOIN autobiographical_events u ON u.id=l.source_event_id
        JOIN autobiographical_events a ON a.id=l.target_event_id
        WHERE l.user_id='creator'
        """
    ).fetchall()
    assert [tuple(row) for row in links] == [(1, 2)]
    db.close()

def test_sync_does_not_link_events_with_mismatched_source_content():
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
            (1, "user", "Texte utilisateur original", timestamp),
            (2, "assistant", "Réponse de Chappie", timestamp),
        ],
    )
    # The first episode points to the right conversation ID but its copied
    # content is stale/corrupted. The assistant episode remains valid.
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "user", "user_statement", "Texte utilisateur modifié", timestamp, 3, timestamp),
            (2, "assistant", "chappie_response", "Réponse de Chappie", timestamp, 1, timestamp),
        ],
    )
    db.commit()

    sync_autobiographical_events(db, "creator")

    links = db.execute(
        "SELECT COUNT(*) FROM autobiographical_links WHERE user_id='creator'"
    ).fetchone()[0]
    assert links == 0
    db.close()




def test_non_positive_conversation_ids_cannot_starve_valid_autobiographical_sync():
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
    # Corrupt legacy IDs sort before the valid conversation and previously
    # consumed the bounded SQL page before Python rejected them.
    db.executemany(
        "INSERT INTO conversations VALUES (?, 'creator', 'user', ?, ?)",
        [
            (
                -(index + 1),
                f"Expérience avec source négative {index}",
                f"2026-11-27T10:{index // 60:02d}:{index % 60:02d}Z",
            )
            for index in range(1005)
        ],
    )
    db.execute(
        "INSERT INTO conversations VALUES (1, 'creator', 'user', ?, ?)",
        ("Souvenir ancien valide", "2020-01-01T10:00:00Z"),
    )
    db.commit()

    result = sync_autobiographical_events(db, "creator", limit=1)

    assert result["inserted"] == 1
    event = db.execute(
        "SELECT source_conversation_id, content FROM autobiographical_events"
    ).fetchone()
    assert tuple(event) == (1, "Souvenir ancien valide")
    db.close()
