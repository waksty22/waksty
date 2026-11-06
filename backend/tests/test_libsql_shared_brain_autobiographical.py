"""V36.8 — real libSQL integration between autobiographical memory and shared brain."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.libsql_adapter import adapt_libsql_connection


@pytest.fixture
def shared_brain_db():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    from memory.autobiographical import (
        init_autobiographical_tables,
        sync_autobiographical_events,
    )

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

    db.execute(
        """INSERT INTO conversations (user_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        ("creator", "user", "J'apprends mieux avec des exemples concrets.", "2026-11-07T10:00:00Z"),
    )
    db.execute(
        """INSERT INTO conversations (user_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        ("creator", "assistant", "Je vais illustrer mes explications.", "2026-11-07T10:00:00Z"),
    )
    db.execute(
        """INSERT INTO conversations (user_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        ("other-user", "user", "Information privée d'un autre utilisateur.", "2026-11-07T10:01:00Z"),
    )
    db.commit()
    sync_autobiographical_events(db, "creator")
    sync_autobiographical_events(db, "other-user")
    try:
        yield db
    finally:
        db.close()


def test_shared_brain_reads_autobiographical_events_from_real_libsql(shared_brain_db):
    from cognition.shared_brain import get_shared_brain_snapshot

    snapshot = get_shared_brain_snapshot(shared_brain_db, "creator")

    assert len(snapshot["autobiographical_events"]) == 2
    assert {event["actor"] for event in snapshot["autobiographical_events"]} == {
        "user", "assistant"
    }
    user_event = next(
        event for event in snapshot["autobiographical_events"]
        if event["actor"] == "user"
    )
    assert user_event["content"] == "J'apprends mieux avec des exemples concrets."
    assert user_event["source_conversation_id"] == 1
    assert snapshot["statistics"]["totals"]["autobiographical_events"] == 2
    assert snapshot["rules"]["unknowns_must_remain_unknown"] is True


def test_shared_brain_context_includes_autobiographical_provenance(shared_brain_db):
    from cognition.shared_brain import (
        format_shared_brain_context,
        get_shared_brain_snapshot,
    )

    snapshot = get_shared_brain_snapshot(shared_brain_db, "creator")
    context = format_shared_brain_context(snapshot)

    assert "ÉPISODES AUTOBIOGRAPHIQUES SOURCÉS" in context
    assert "source_conversation_id" in context
    assert "J'apprends mieux avec des exemples concrets." in context
    assert "une hypothèse n'est pas un fait" in context


def test_shared_brain_autobiographical_data_is_user_isolated(shared_brain_db):
    from cognition.shared_brain import get_shared_brain_snapshot

    creator = get_shared_brain_snapshot(shared_brain_db, "creator")
    other = get_shared_brain_snapshot(shared_brain_db, "other-user")
    unknown = get_shared_brain_snapshot(shared_brain_db, "unknown-user")

    assert len(creator["autobiographical_events"]) == 2
    assert len(other["autobiographical_events"]) == 1
    assert other["autobiographical_events"][0]["content"] == (
        "Information privée d'un autre utilisateur."
    )
    assert unknown["autobiographical_events"] == []
    assert unknown["statistics"]["totals"]["autobiographical_events"] == 0


def test_shared_brain_tolerates_absent_autobiographical_tables_on_libsql():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        from cognition.shared_brain import get_shared_brain_snapshot

        snapshot = get_shared_brain_snapshot(db, "creator")
        assert snapshot["autobiographical_events"] == []
        assert snapshot["statistics"]["totals"]["autobiographical_events"] == 0
    finally:
        db.close()
