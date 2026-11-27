"""Atomicity regression tests for saving a conversation and its memories."""
from __future__ import annotations

import sqlite3


def test_conversation_save_rolls_back_source_journal_and_autobiography_together(
    monkeypatch, tmp_path
):
    import server

    database_path = tmp_path / "atomic-conversation.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_SQLITE_PATH", str(database_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.delenv("CHAPPIE_TURSO_CUTOVER_READY", raising=False)
    monkeypatch.delenv("CHAPPIE_TURSO_FRESH_START", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    server.init_db()

    original_sync = server.sync_autobiographical_events

    def sync_then_fail(*args, **kwargs):
        # Let the real synchronizer write its event/link rows into the open
        # transaction, then simulate a failure before the transaction commits.
        original_sync(*args, **kwargs)
        raise RuntimeError("simulated autobiographical index failure")

    monkeypatch.setattr(server, "sync_autobiographical_events", sync_then_fail)

    try:
        server.save_conversation_turn(
            "creator",
            "J'ai appris le mot luciole.",
            "Je retiens le mot luciole.",
        )
    except RuntimeError as exc:
        assert "simulated autobiographical index failure" in str(exc)
    else:
        raise AssertionError("The injected indexing failure must propagate")

    with sqlite3.connect(database_path) as db:
        expected_empty = {
            "conversations",
            "journal",
            "autobiographical_events",
            "autobiographical_links",
        }
        for table in expected_empty:
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} retained {count} partial rows"
