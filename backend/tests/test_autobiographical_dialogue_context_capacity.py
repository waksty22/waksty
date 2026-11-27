"""Dialogue-aware autobiographical recall under a strict result bound."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import (
    init_autobiographical_tables,
    search_autobiographical_events,
)


def test_full_recall_page_preserves_reply_linked_to_strongest_user_memory():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)
    events = [
        ("creator", 1, "user", "user_statement",
         "J'ai une horloge astronomique rouge dans le salon",
         "2026-01-01T10:00:00Z", 3, "2026-01-01T10:00:00Z"),
        ("creator", 2, "assistant", "chappie_response",
         "Je note cette information pour notre prochaine discussion",
         "2026-01-01T10:00:00Z", 1, "2026-01-01T10:00:00Z"),
        ("creator", 3, "user", "user_statement",
         "J'ai aussi un objet astronomique bleu dans l'atelier",
         "2026-01-02T10:00:00Z", 3, "2026-01-02T10:00:00Z"),
    ]
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        events,
    )
    db.execute(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', 1, 2, 'same_dialogue_turn', '2026-01-01T10:00:00Z')
        """
    )
    db.commit()

    results = search_autobiographical_events(
        db, "creator", "horloge astronomique", limit=2
    )

    assert len(results) == 2
    source = next(item for item in results if item["id"] == 1)
    reply = next(item for item in results if item["id"] == 2)
    assert source["actor"] == "user"
    assert source["dialogue_context"] is False
    assert reply["actor"] == "assistant"
    assert reply["dialogue_context"] is True
    assert reply["relevance_score"] == 0.0
    assert reply["matched_terms"] == []
    db.close()


def test_single_result_limit_does_not_exceed_bound_for_dialogue_pair():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, ?, ?, ?, ?, 3, ?)
        """,
        [
            (1, "user", "user_statement", "horloge astronomique rouge",
             "2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z"),
            (2, "assistant", "chappie_response", "Je note cette horloge",
             "2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z"),
        ],
    )
    db.execute(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', 1, 2, 'same_dialogue_turn', '2026-01-01T10:00:00Z')
        """
    )
    db.commit()

    results = search_autobiographical_events(
        db, "creator", "horloge astronomique", limit=1
    )

    assert len(results) == 1
    assert results[0]["id"] == 1
    assert results[0]["dialogue_context"] is False
    db.close()
