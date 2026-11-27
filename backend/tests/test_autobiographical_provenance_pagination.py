"""Invalid provenance must not starve chronological autobiographical pages."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import init_autobiographical_tables, list_autobiographical_events


def test_recent_ungrounded_events_do_not_starve_valid_older_page_entries():
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
    db.execute(
        "INSERT INTO conversations VALUES (1, 'creator', 'user', 'Souvenir ancien valide', '2025-01-01T10:00:00Z')"
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (id, user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES (1, 'creator', 1, 'user', 'user_statement',
                'Souvenir ancien valide', '2025-01-01T10:00:00Z', 3,
                '2025-01-01T10:00:00Z')
        """
    )
    for event_id in range(2, 6):
        db.execute(
            """
            INSERT INTO conversations
                (id, user_id, role, content, created_at)
            VALUES (?, 'creator', 'user', ?, ?)
            """,
            (event_id, f"Source réelle {event_id}", f"2026-11-27T10:0{event_id}:00Z"),
        )
        db.execute(
            """
            INSERT INTO autobiographical_events
                (id, user_id, source_conversation_id, actor, event_type, content,
                 happened_at, importance, created_at)
            VALUES (?, 'creator', ?, 'user', 'user_statement', ?,
                    ?, 3, ?)
            """,
            (
                event_id,
                event_id,
                f"Contenu copié incohérent {event_id}",
                f"2026-11-27T10:0{event_id}:00Z",
                f"2026-11-27T10:0{event_id}:00Z",
            ),
        )
    db.commit()

    page = list_autobiographical_events(db, "creator", limit=1)

    assert [item["id"] for item in page] == [1]
    db.close()
