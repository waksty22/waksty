"""V50.44 — isolated tests for Chappie's persistent memory pipeline.

The tests use temporary SQLite files and real Chappie persistence functions.
They never connect to Render, Turso, Gemini, or any production service.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from cognition.event_receipts import init_cognitive_event_receipt_table
from cognition.shared_brain import get_shared_brain_snapshot
from learning.language import (
    advance_word,
    init_language_tables,
    record_heard_text,
)
from memory.autobiographical import init_autobiographical_tables
from memory.conversation_outbox import init_conversation_finalization_outbox


@pytest.fixture
def memory_pipeline(tmp_path, monkeypatch):
    path = tmp_path / "memory-pipeline.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_conversations_user_id
                ON conversations(user_id, id DESC);
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                entry TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                through_conversation_id INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, through_conversation_id)
            );
            CREATE TABLE conversation_turn_receipts (
                user_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, turn_id)
            );
        """)
        init_autobiographical_tables(db)
        init_language_tables(db)
        init_cognitive_event_receipt_table(db)
        init_conversation_finalization_outbox(db)
        db.commit()

    @contextmanager
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(server, "db_connection", connect)
    monkeypatch.setattr(server, "valid_user", lambda user_id: user_id)
    return path, connect


def _counts(connect):
    with connect() as db:
        return {
            "conversations": db.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()[0],
            "journal": db.execute(
                "SELECT COUNT(*) FROM journal"
            ).fetchone()[0],
            "outbox_pending": db.execute(
                "SELECT COUNT(*) FROM conversation_finalization_outbox WHERE status='pending'"
            ).fetchone()[0],
            "outbox_completed": db.execute(
                "SELECT COUNT(*) FROM conversation_finalization_outbox WHERE status='completed'"
            ).fetchone()[0],
            "autobiographical": db.execute(
                "SELECT COUNT(*) FROM autobiographical_events"
            ).fetchone()[0],
        }


def test_chat_and_live_turns_share_memory_after_close_reopen(memory_pipeline):
    _, connect = memory_pipeline

    with connect() as db:
        assert server.save_conversation_turn(
            "creator", "Je préfère le bleu.", "Je retiens cette préférence.",
            source="conversation", turn_id="chat-0001", db=db,
        )

    # A second interface writes to the same persistent conversation store.
    with connect() as db:
        assert server.save_conversation_turn(
            "creator", "J'ai entendu le mot luciole.", "Luciole.",
            source="gemini_live", turn_id="live-0001", db=db,
        )

    # Simulate a process restart: all connections have been closed.
    recovery = server.recover_pending_conversation_finalizations()
    assert recovery == {"users_checked": 1, "users_with_pending_failures": 0}

    with connect() as db:
        snapshot = get_shared_brain_snapshot(db, "creator", limit=20)
        episodes = snapshot["autobiographical_events"]
        content = {item["content"] for item in episodes}
        assert {
            "Je préfère le bleu.",
            "Je retiens cette préférence.",
            "J'ai entendu le mot luciole.",
            "Luciole.",
        }.issubset(content)
        assert snapshot["statistics"]["totals"]["autobiographical_events"] == 4

    counts = _counts(connect)
    assert counts == {
        "conversations": 4,
        "journal": 2,
        "outbox_pending": 0,
        "outbox_completed": 2,
        "autobiographical": 4,
    }


def test_turn_and_outbox_roll_back_as_one_transaction(memory_pipeline):
    _, connect = memory_pipeline

    with pytest.raises(RuntimeError, match="simulated crash"):
        with connect() as db:
            assert server.save_conversation_turn(
                "creator", "Cette phrase ne doit pas survivre.",
                "Cette réponse non plus.",
                source="gemini_live", turn_id="live-rollback", db=db,
            )
            raise RuntimeError("simulated crash before commit")

    counts = _counts(connect)
    assert counts == {
        "conversations": 0,
        "journal": 0,
        "outbox_pending": 0,
        "outbox_completed": 0,
        "autobiographical": 0,
    }


def test_pending_finalization_survives_restart_and_retries(memory_pipeline, monkeypatch):
    _, connect = memory_pipeline

    with connect() as db:
        assert server.save_conversation_turn(
            "creator", "Je découvre une étoile.", "Une étoile.",
            source="gemini_live", turn_id="live-pending", db=db,
        )

    original_sync = server.sync_autobiographical_events

    def fail_once(*args, **kwargs):
        raise RuntimeError("temporary memory indexing failure")

    monkeypatch.setattr(server, "sync_autobiographical_events", fail_once)
    server.finalize_conversation_turn("creator")

    with connect() as db:
        pending = db.execute(
            "SELECT attempts, last_error FROM conversation_finalization_outbox "
            "WHERE status='pending'"
        ).fetchone()
        assert pending["attempts"] == 1
        assert "temporary memory indexing failure" in pending["last_error"]

    # Simulate a later process start after the dependency recovers.
    monkeypatch.setattr(server, "sync_autobiographical_events", original_sync)
    result = server.recover_pending_conversation_finalizations()
    assert result == {"users_checked": 1, "users_with_pending_failures": 0}
    assert _counts(connect)["outbox_completed"] == 1
    assert _counts(connect)["autobiographical"] == 2


def test_finalization_is_idempotent_after_success(memory_pipeline):
    _, connect = memory_pipeline

    with connect() as db:
        server.save_conversation_turn(
            "creator", "Je vois une lune.", "La lune.",
            source="conversation", turn_id="chat-idempotent", db=db,
        )

    server.finalize_conversation_turn("creator")
    server.finalize_conversation_turn("creator")

    counts = _counts(connect)
    assert counts["autobiographical"] == 2
    assert counts["outbox_completed"] == 1
    assert counts["outbox_pending"] == 0


def test_vocabulary_event_receipt_and_learning_stage_survive_reopen(memory_pipeline):
    _, connect = memory_pipeline

    with connect() as db:
        first = record_heard_text(
            db, "creator", "luciole", event_id="audio-event-0001"
        )
        replay = record_heard_text(
            db, "creator", "luciole", event_id="audio-event-0001"
        )
        assert len(first) == 1
        assert replay == []
        assert first[0]["state"] == "heard"
        assert first[0]["exposure_count"] == 1

        imitated = advance_word(
            db, "creator", "luciole", "imitated",
            evidence="Imitation supervisée en test",
        )
        assert imitated["state"] == "imitated"
        with pytest.raises(ValueError, match="étape par étape"):
            advance_word(db, "creator", "luciole", "understood")

    with connect() as db:
        word = db.execute(
            "SELECT state, exposure_count FROM personal_vocabulary "
            "WHERE user_id='creator' AND word='luciole'"
        ).fetchone()
        assert tuple(word) == ("imitated", 1)
        recognized = advance_word(
            db, "creator", "luciole", "recognized",
            evidence="Reconnaissance vérifiée après réouverture",
        )
        assert recognized["state"] == "recognized"


def test_memory_is_scoped_to_the_correct_user(memory_pipeline):
    _, connect = memory_pipeline

    with connect() as db:
        server.save_conversation_turn(
            "creator", "Souvenir du créateur.", "Réponse privée.",
            source="conversation", turn_id="creator-turn", db=db,
        )
        server.save_conversation_turn(
            "another-user", "Autre souvenir.", "Autre réponse.",
            source="conversation", turn_id="other-turn", db=db,
        )

    server.finalize_conversation_turn("creator")
    server.finalize_conversation_turn("another-user")

    with connect() as db:
        creator = get_shared_brain_snapshot(db, "creator", limit=20)
        other = get_shared_brain_snapshot(db, "another-user", limit=20)
        creator_text = {row["content"] for row in creator["autobiographical_events"]}
        other_text = {row["content"] for row in other["autobiographical_events"]}
        assert "Souvenir du créateur." in creator_text
        assert "Autre souvenir." not in creator_text
        assert "Autre souvenir." in other_text
        assert "Souvenir du créateur." not in other_text
