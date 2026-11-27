"""Full-history recall for long-lived autobiographical journals."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    init_autobiographical_tables,
    search_autobiographical_events,
    find_related_autobiographical_events,
)


def test_autobiographical_search_and_related_recall_reach_past_2000_events():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES (?, ?, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        [
            ("creator", 1, "Le Créateur a montré une horloge astronomique dans le salon",
             "2025-01-01T10:00:00Z", "2025-01-01T10:00:00Z"),
            ("creator", 2, "Réparation horloge mécanique ancienne",
             "2025-01-02T10:00:00Z", "2025-01-02T10:00:00Z"),
            ("creator", 3, "Une horloge mécanique se trouve dans l'atelier",
             "2025-01-03T10:00:00Z", "2025-01-03T10:00:00Z"),
        ],
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, 'user', 'user_statement', ?, ?, 1, ?)
        """,
        [
            (index, f"Épisode récent sans rapport numéro {index}",
             f"2026-11-{(index % 27) + 1:02d}T10:00:00Z",
             f"2026-11-{(index % 27) + 1:02d}T10:00:00Z")
            for index in range(4, 2205)
        ],
    )
    db.commit()

    recalled = search_autobiographical_events(
        db, "creator", "horloge astronomique", limit=5
    )
    assert recalled
    assert recalled[0]["id"] == 1
    assert recalled[0]["matched_terms"] == ["horloge", "astronomique"]

    related = find_related_autobiographical_events(
        db, "creator", event_id=2, limit=5
    )
    assert related
    assert related[0]["id"] == 3
    assert related[0]["relation_status"] == "candidate_only"

    # The search must not cross user boundaries while scanning older pages.
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('another-user', 9999, 'user', 'user_statement',
                'horloge astronomique privée', '2025-01-01T10:00:00Z',
                5, '2025-01-01T10:00:00Z')
        """
    )
    assert all(
        "privée" not in item["content"]
        for item in search_autobiographical_events(
            db, "creator", "horloge astronomique", limit=5
        )
    )
    db.close()



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

    related = find_related_autobiographical_events(
        db, "creator", event_id=1, limit=5
    )
    assert related == []
    assert find_related_autobiographical_events(
        db, "creator", event_id=3, limit=5
    ) == []
    db.close()
