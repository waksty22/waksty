import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.autobiographical import (
    init_autobiographical_tables,
    search_autobiographical_events,
)


def make_db():
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
    return db


def add_event(db, event_id, user_id, actor, content, importance=2):
    db.execute(
        "INSERT OR IGNORE INTO conversations VALUES (?, ?, ?, ?, ?)",
        (event_id, user_id, actor, content, f"2026-11-0{event_id}T10:00:00+00:00"),
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (id, user_id, source_conversation_id, actor, event_type,
             content, happened_at, importance, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, user_id, event_id, actor,
         "user_statement" if actor == "user" else "chappie_response",
         content, f"2026-11-0{event_id}T10:00:00+00:00",
         importance, f"2026-11-0{event_id}T10:00:00+00:00"),
    )


def test_autobiographical_search_matches_multiple_terms_and_accents():
    db = make_db()
    add_event(db, 1, "creator", "user",
              "Nous avons parlé du déménagement de ma sœur à Rennes.", 2)
    add_event(db, 2, "creator", "user",
              "Une ancienne conversation sur le basket.", 5)

    results = search_autobiographical_events(
        db, "creator", "demenagement soeur", limit=5
    )

    assert results
    assert results[0]["id"] == 1
    assert set(results[0]["matched_terms"]) == {"demenagement", "soeur"}
    db.close()


def test_autobiographical_search_adds_only_explicit_same_turn_reply():
    db = make_db()
    add_event(db, 1, "creator", "user",
              "J'ai acheté un vélo rouge hier.", 3)
    add_event(db, 2, "creator", "assistant",
              "Je me souviens de ce que tu m'as raconté hier.", 1)
    db.execute(
        """
        INSERT INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        VALUES ('creator', 1, 2, 'same_dialogue_turn', '2026-11-01T10:00:00+00:00')
        """
    )

    results = search_autobiographical_events(
        db, "creator", "vélo rouge", limit=5
    )

    assert [item["id"] for item in results] == [1, 2]
    assert results[0]["dialogue_context"] is False
    assert results[1]["dialogue_context"] is True
    assert results[1]["relevance_score"] == 0.0
    db.close()


def test_autobiographical_search_never_returns_another_users_events():
    db = make_db()
    add_event(db, 1, "alice", "user", "Le voyage à Paris.")
    add_event(db, 2, "bob", "user", "Le voyage à Paris.")

    results = search_autobiographical_events(db, "alice", "voyage Paris")

    assert [item["id"] for item in results] == [1]
    db.close()


def test_autobiographical_search_empty_or_stopword_only_query_is_safe():
    db = make_db()
    add_event(db, 1, "creator", "user", "Une discussion importante.")

    assert search_autobiographical_events(db, "creator", "") == []
    assert search_autobiographical_events(db, "creator", "et ou le") == []
    db.close()
