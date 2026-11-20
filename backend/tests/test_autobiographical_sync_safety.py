"""Safety tests for autobiographical backfill and transaction ownership."""
import sqlite3

from memory.autobiographical import (
    init_autobiographical_tables,
    sync_autobiographical_events,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    init_autobiographical_tables(db)
    return db


def add_messages(db, count, user_id="creator"):
    db.executemany(
        """
        INSERT INTO conversations(user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                user_id,
                "user" if index % 2 == 0 else "assistant",
                f"message {index}",
                f"2026-11-20T00:00:{index:02d}+00:00",
            )
            for index in range(count)
        ],
    )
    db.commit()


def test_autobiographical_sync_is_idempotent_across_repeated_calls():
    db = make_db()
    add_messages(db, 6)

    first = sync_autobiographical_events(db, "creator")
    second = sync_autobiographical_events(db, "creator")

    assert first["inserted"] == 6
    assert second["inserted"] == 0
    assert second["total_events"] == 6
    assert db.execute(
        "SELECT COUNT(*) FROM autobiographical_events WHERE user_id='creator'"
    ).fetchone()[0] == 6
    db.close()


def test_autobiographical_sync_respects_batch_limit_and_makes_progress():
    db = make_db()
    add_messages(db, 5)

    results = [
        sync_autobiographical_events(db, "creator", limit=2),
        sync_autobiographical_events(db, "creator", limit=2),
        sync_autobiographical_events(db, "creator", limit=2),
        sync_autobiographical_events(db, "creator", limit=2),
    ]

    assert [result["inserted"] for result in results] == [2, 2, 1, 0]
    assert results[-1]["total_events"] == 5
    db.close()


def test_autobiographical_sync_commit_false_preserves_caller_rollback():
    db = make_db()
    add_messages(db, 2)

    result = sync_autobiographical_events(db, "creator", commit=False)

    assert result["inserted"] == 2
    assert db.in_transaction
    assert db.execute(
        "SELECT COUNT(*) FROM autobiographical_events"
    ).fetchone()[0] == 2

    db.rollback()

    assert db.execute(
        "SELECT COUNT(*) FROM autobiographical_events"
    ).fetchone()[0] == 0
    db.close()
