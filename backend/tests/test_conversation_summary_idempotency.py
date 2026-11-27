"""Regression tests for idempotent autobiographical summary journaling."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager


import server


class _StaleSummaryCursor:
    def fetchone(self):
        return None


class _StaleSummaryReadConnection:
    """Simulate a concurrent writer winning after our summary cursor read."""

    def __init__(self, connection):
        self.connection = connection
        self.stale_read_pending = True

    def execute(self, sql, params=()):
        if (
            self.stale_read_pending
            and "SELECT through_conversation_id" in sql
        ):
            self.stale_read_pending = False
            return _StaleSummaryCursor()
        return self.connection.execute(sql, params)

    def commit(self):
        return self.connection.commit()


def test_concurrent_summary_insert_does_not_duplicate_journal(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE conversation_summaries (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            through_conversation_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, through_conversation_id)
        );
        CREATE TABLE journal (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            entry TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    for index in range(10):
        db.execute(
            """
            INSERT INTO conversations(user_id, role, content, created_at)
            VALUES ('creator', ?, ?, ?)
            """,
            (
                "user" if index % 2 == 0 else "assistant",
                f"Message {index}",
                f"2026-11-27T16:00:{index:02d}+00:00",
            ),
        )

    # Represents a concurrent worker that committed after this worker read
    # the previous summary cursor but before its INSERT OR IGNORE.
    db.execute(
        """
        INSERT INTO conversation_summaries(
            user_id, summary, through_conversation_id, created_at
        ) VALUES ('creator', 'Résumé déjà consolidé', 10, '2026-11-27T16:01:00+00:00')
        """
    )
    db.commit()
    wrapped = _StaleSummaryReadConnection(db)

    @contextmanager
    def fake_db_connection():
        yield wrapped

    monkeypatch.setattr(server, "db_connection", fake_db_connection)
    result = server.consolidate_conversation("creator")

    assert result["created"] is False
    assert result["summary"] == "Résumé déjà consolidé"
    assert result["through_id"] == 10
    assert db.execute(
        "SELECT COUNT(*) FROM conversation_summaries WHERE user_id='creator'"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM journal WHERE user_id='creator' AND kind='summary'"
    ).fetchone()[0] == 0
    db.close()
