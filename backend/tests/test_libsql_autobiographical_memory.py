"""Real autobiographical-memory integration tests against local libSQL only."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.libsql_adapter import adapt_libsql_connection


@pytest.fixture
def autobiographical_db():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    from memory.autobiographical import init_autobiographical_tables

    # Minimal source table matching the production conversation columns.
    db.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    init_autobiographical_tables(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def _insert_conversation(db, user_id, role, content, created_at):
    cursor = db.execute(
        """INSERT INTO conversations (user_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        (user_id, role, content, created_at),
    )
    return cursor.lastrowid


def test_real_libsql_autobiographical_sync_is_idempotent_and_links_dialogue(autobiographical_db):
    from memory.autobiographical import (
        autobiographical_statistics,
        init_autobiographical_tables,
        list_autobiographical_events,
        sync_autobiographical_events,
    )

    db = autobiographical_db
    timestamp = "2026-11-07T12:00:00+01:00"
    _insert_conversation(db, "creator", "user", "Je préfère apprendre par la pratique.", timestamp)
    _insert_conversation(db, "creator", "assistant", "Nous allons procéder étape par étape.", timestamp)
    _insert_conversation(db, "another-user", "user", "Souvenir strictement privé.", timestamp)
    db.commit()

    first = sync_autobiographical_events(db, "creator")
    assert first == {"inserted": 2, "total_events": 2, "dialogue_links": 1}

    # Reinitializing the schema and syncing again must not duplicate events.
    init_autobiographical_tables(db)
    second = sync_autobiographical_events(db, "creator")
    assert second == {"inserted": 0, "total_events": 2, "dialogue_links": 1}

    events = list_autobiographical_events(db, "creator")
    assert len(events) == 2
    assert {event["actor"] for event in events} == {"user", "assistant"}
    assert all(event["happened_at"] == timestamp for event in events)

    stats = autobiographical_statistics(db, "creator")
    assert stats == {
        "total_events": 2,
        "user_events": 1,
        "chappie_events": 1,
        "dialogue_links": 1,
    }
    assert autobiographical_statistics(db, "another-user")["total_events"] == 0


def test_real_libsql_autobiographical_search_pagination_and_literal_wildcards(autobiographical_db):
    from memory.autobiographical import (
        list_autobiographical_events,
        search_autobiographical_events,
        sync_autobiographical_events,
    )

    db = autobiographical_db
    _insert_conversation(db, "creator", "user", "Le symbole 100% est important.", "t1")
    _insert_conversation(db, "creator", "user", "Le caractère _ doit rester littéral.", "t2")
    _insert_conversation(db, "creator", "user", "Une guitare acoustique.", "t3")
    _insert_conversation(db, "another-user", "user", "100% secret.", "t4")
    db.commit()

    result = sync_autobiographical_events(db, "creator")
    assert result["inserted"] == 3

    assert len(search_autobiographical_events(db, "creator", "100%")) == 1
    assert len(search_autobiographical_events(db, "creator", "_")) == 1
    assert len(search_autobiographical_events(db, "creator", "GUITARE")) == 1
    assert search_autobiographical_events(db, "another-user", "100%") == []

    page_one = list_autobiographical_events(db, "creator", limit=2)
    page_two = list_autobiographical_events(
        db, "creator", limit=2, before_id=page_one[-1]["id"]
    )
    assert len(page_one) == 2
    assert len(page_two) == 1
    assert page_one[0]["id"] > page_one[-1]["id"] > page_two[0]["id"]


def test_real_libsql_autobiographical_sync_ignores_unsupported_and_empty_roles(autobiographical_db):
    from memory.autobiographical import sync_autobiographical_events

    db = autobiographical_db
    _insert_conversation(db, "creator", "system", "Instruction interne.", "t1")
    _insert_conversation(db, "creator", "user", "   ", "t2")
    _insert_conversation(db, "creator", "user", "Souvenir conservé.", "t3")
    db.commit()

    result = sync_autobiographical_events(db, "creator")
    assert result["inserted"] == 1
    assert result["total_events"] == 1
