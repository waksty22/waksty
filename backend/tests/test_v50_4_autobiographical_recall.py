import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.autobiographical import (
    init_autobiographical_tables,
    sync_autobiographical_events,
    search_autobiographical_events,
    list_autobiographical_events,
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


def test_autobiographical_links_pair_consecutive_messages_not_shared_timestamps():
    db = make_db()
    timestamp = "2026-11-19T10:00:00+00:00"
    db.executemany(
        "INSERT INTO conversations(id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "creator", "user", "Premier message", timestamp),
            (2, "creator", "assistant", "Première réponse", timestamp),
            (3, "creator", "user", "Deuxième message", timestamp),
            (4, "creator", "assistant", "Deuxième réponse", timestamp),
        ],
    )

    result = sync_autobiographical_events(db, "creator")

    links = db.execute(
        """
        SELECT u.source_conversation_id AS user_source,
               a.source_conversation_id AS assistant_source
        FROM autobiographical_links l
        JOIN autobiographical_events u ON u.id=l.source_event_id
        JOIN autobiographical_events a ON a.id=l.target_event_id
        WHERE l.user_id='creator'
        ORDER BY u.source_conversation_id
        """
    ).fetchall()

    assert result["inserted"] == 4
    assert [(row["user_source"], row["assistant_source"]) for row in links] == [
        (1, 2), (3, 4)
    ]
    db.close()


def test_autobiographical_link_does_not_pair_nonconsecutive_messages():
    db = make_db()
    timestamp = "2026-11-19T10:00:00+00:00"
    db.executemany(
        "INSERT INTO conversations(id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "creator", "user", "Question", timestamp),
            (2, "creator", "user", "Autre question", timestamp),
            (3, "creator", "assistant", "Réponse", timestamp),
        ],
    )

    sync_autobiographical_events(db, "creator")

    assert db.execute(
        "SELECT COUNT(*) FROM autobiographical_links WHERE user_id='creator'"
    ).fetchone()[0] == 0
    db.close()



def test_autobiographical_search_uses_complete_tokens_not_substrings():
    db = make_db()
    add_event(db, 1, "creator", "user",
              "Nous partageons une information importante.")
    add_event(db, 2, "creator", "user",
              "L'art est un sujet différent.")

    results = search_autobiographical_events(db, "creator", "art", limit=5)

    assert len(results) == 1
    assert results[0]["id"] == 2
    assert results[0]["matched_terms"] == ["art"]
    db.close()


import pytest


@pytest.mark.parametrize("bad_limit", [True, False, 1.5, "10", 0, -1])
def test_autobiographical_memory_rejects_coerced_or_invalid_limits(bad_limit):
    from memory.autobiographical import (
        find_related_autobiographical_events,
        list_autobiographical_events,
        sync_autobiographical_events,
    )

    db = make_db()
    with pytest.raises(ValueError):
        sync_autobiographical_events(db, "creator", limit=bad_limit)
    with pytest.raises(ValueError):
        list_autobiographical_events(db, "creator", limit=bad_limit)
    with pytest.raises(ValueError):
        search_autobiographical_events(db, "creator", "souvenir", limit=bad_limit)
    with pytest.raises(ValueError):
        find_related_autobiographical_events(db, "creator", 1, limit=bad_limit)
    assert db.execute("SELECT COUNT(*) FROM autobiographical_events").fetchone()[0] == 0
    db.close()


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1", 0, -1])
def test_autobiographical_memory_rejects_coerced_identifiers(bad_id):
    from memory.autobiographical import (
        find_related_autobiographical_events,
        list_autobiographical_events,
    )

    db = make_db()
    add_event(db, 1, "creator", "user", "Un souvenir vérifiable.")
    with pytest.raises(ValueError):
        list_autobiographical_events(db, "creator", before_id=bad_id)
    with pytest.raises(ValueError):
        find_related_autobiographical_events(db, "creator", bad_id)
    db.close()


@pytest.mark.parametrize("bad_query", [123, True, [], {}])
def test_autobiographical_search_rejects_non_text_queries(bad_query):
    db = make_db()
    with pytest.raises(ValueError, match="texte"):
        search_autobiographical_events(db, "creator", bad_query)
    db.close()


@pytest.mark.parametrize("bad_user", [None, 123, True, "", "   ", "x" * 81])
def test_autobiographical_memory_rejects_invalid_user_ids(bad_user):
    from memory.autobiographical import autobiographical_statistics

    db = make_db()
    with pytest.raises(ValueError, match="utilisateur"):
        sync_autobiographical_events(db, bad_user)
    with pytest.raises(ValueError, match="utilisateur"):
        list_autobiographical_events(db, bad_user)
    with pytest.raises(ValueError, match="utilisateur"):
        search_autobiographical_events(db, bad_user, "souvenir")
    with pytest.raises(ValueError, match="utilisateur"):
        autobiographical_statistics(db, bad_user)
    db.close()


def test_autobiographical_sync_rejects_coerced_commit_flag():
    db = make_db()
    with pytest.raises(ValueError, match="booléen"):
        sync_autobiographical_events(db, "creator", commit=1)
    assert db.execute("SELECT COUNT(*) FROM autobiographical_events").fetchone()[0] == 0
    db.close()



def test_autobiographical_links_ignore_global_id_gaps_from_other_users():
    db = make_db()
    timestamp = "2026-11-24T10:00:00+00:00"
    db.executemany(
        "INSERT INTO conversations(id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (10, "creator", "user", "Question du créateur", timestamp),
            (11, "another-user", "user", "Question indépendante", timestamp),
            (12, "creator", "assistant", "Réponse au créateur", timestamp),
        ],
    )

    result = sync_autobiographical_events(db, "creator")

    links = db.execute(
        """
        SELECT u.source_conversation_id AS user_source,
               a.source_conversation_id AS assistant_source
        FROM autobiographical_links l
        JOIN autobiographical_events u ON u.id=l.source_event_id
        JOIN autobiographical_events a ON a.id=l.target_event_id
        WHERE l.user_id='creator'
        """
    ).fetchall()

    assert result["inserted"] == 2
    assert [(row["user_source"], row["assistant_source"]) for row in links] == [
        (10, 12)
    ]
    db.close()


def test_autobiographical_links_still_reject_same_user_intervening_message():
    db = make_db()
    timestamp = "2026-11-24T10:00:00+00:00"
    db.executemany(
        "INSERT INTO conversations(id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (20, "creator", "user", "Premier message", timestamp),
            (21, "another-user", "user", "Message indépendant", timestamp),
            (22, "creator", "user", "Second message", timestamp),
            (23, "creator", "assistant", "Réponse", timestamp),
        ],
    )

    sync_autobiographical_events(db, "creator")

    links = db.execute(
        "SELECT source_event_id, target_event_id FROM autobiographical_links WHERE user_id='creator'"
    ).fetchall()
    linked_sources = [
        (
            db.execute(
                "SELECT source_conversation_id FROM autobiographical_events WHERE id=?",
                (row["source_event_id"],),
            ).fetchone()[0],
            db.execute(
                "SELECT source_conversation_id FROM autobiographical_events WHERE id=?",
                (row["target_event_id"],),
            ).fetchone()[0],
        )
        for row in links
    ]

    assert linked_sources == [(22, 23)]
    db.close()
