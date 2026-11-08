"""V50.40 — durable post-commit outbox contracts."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest
import server
from memory.conversation_outbox import (
    init_conversation_finalization_outbox,
    enqueue_conversation_finalization,
    list_pending_conversation_finalizations,
    mark_conversation_finalization,
)


def test_outbox_enqueue_is_idempotent_and_tracks_completion(tmp_path):
    db = sqlite3.connect(tmp_path / "outbox.sqlite3")
    db.row_factory = sqlite3.Row
    init_conversation_finalization_outbox(db)

    assert enqueue_conversation_finalization(db, "creator", 42) is True
    assert enqueue_conversation_finalization(db, "creator", 42) is False
    pending = list_pending_conversation_finalizations(db)
    assert len(pending) == 1
    assert pending[0]["through_conversation_id"] == 42

    mark_conversation_finalization(db, pending[0]["id"], error="temporary sync failure")
    db.commit()
    retry = list_pending_conversation_finalizations(db)
    assert len(retry) == 1
    row = db.execute(
        "SELECT attempts, status, last_error FROM conversation_finalization_outbox"
    ).fetchone()
    assert row["attempts"] == 1
    assert row["status"] == "pending"
    assert row["last_error"] == "temporary sync failure"

    mark_conversation_finalization(db, retry[0]["id"])
    db.commit()
    assert list_pending_conversation_finalizations(db) == []
    completed = db.execute(
        "SELECT attempts, status, last_error, completed_at "
        "FROM conversation_finalization_outbox"
    ).fetchone()
    assert completed["attempts"] == 2
    assert completed["status"] == "completed"
    assert completed["last_error"] == ""
    assert completed["completed_at"]
    db.close()


def test_outbox_enqueue_rolls_back_with_conversation_transaction(tmp_path):
    db = sqlite3.connect(tmp_path / "outbox-rollback.sqlite3")
    db.row_factory = sqlite3.Row
    init_conversation_finalization_outbox(db)
    db.execute("BEGIN")
    enqueue_conversation_finalization(db, "creator", 7)
    db.rollback()
    assert list_pending_conversation_finalizations(db) == []
    db.close()


def test_save_conversation_turn_enqueues_in_the_callers_transaction(tmp_path, monkeypatch):
    path = tmp_path / "conversation-outbox.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                entry TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

    @contextmanager
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(server, "db_connection", connect)
    monkeypatch.setattr(server, "valid_user", lambda value: value)
    # Production initializes the additive outbox schema during application startup.
    with connect() as db:
        init_conversation_finalization_outbox(db)
    monkeypatch.setattr(
        server, "finalize_conversation_turn",
        lambda _user: (_ for _ in ()).throw(AssertionError("must run after caller commit")),
    )

    with pytest.raises(RuntimeError):
        with connect() as db:
            assert server.save_conversation_turn(
                "creator", "Tour atomique.", "Réponse.",
                turn_id="outbox-turn-0001", db=db,
            )
            raise RuntimeError("rollback before commit")

    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM conversation_finalization_outbox").fetchone()[0] == 0

    with connect() as db:
        assert server.save_conversation_turn(
            "creator", "Tour atomique.", "Réponse.",
            turn_id="outbox-turn-0002", db=db,
        )

    with connect() as db:
        jobs = list_pending_conversation_finalizations(db)
        assert len(jobs) == 1
        assert jobs[0]["user_id"] == "creator"
        assert jobs[0]["through_conversation_id"] == 2
