"""V50.46 — verify cognitive state reconstruction after DB close/reopen."""
from pathlib import Path
import sqlite3
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.development import init_development_tables, record_affective_snapshot
from cognition.event_receipts import init_cognitive_event_receipt_table
from cognition.shared_brain import (
    get_shared_brain_snapshot,
    format_shared_brain_context,
)
from learning.language import init_language_tables, record_heard_text
from learning.sensory import init_sensory_tables, record_observation
from memory.conversation_outbox import (
    init_conversation_finalization_outbox,
    enqueue_conversation_finalization,
    list_pending_conversation_finalizations,
    mark_conversation_finalization,
)


def open_db(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def initialize(db):
    init_cognitive_event_receipt_table(db)
    init_development_tables(db)
    init_language_tables(db)
    init_sensory_tables(db)
    init_conversation_finalization_outbox(db)
    db.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()


def test_shared_brain_reconstructs_persisted_cognition_after_reopen(tmp_path):
    path = tmp_path / "chappie-restart.sqlite3"
    db = open_db(path)
    initialize(db)

    db.execute(
        "INSERT INTO conversations(user_id, role, content) VALUES (?, ?, ?)",
        ("creator", "user", "Regarde cette luciole."),
    )
    record_heard_text(
        db, "creator", "luciole forêt", event_id="chat-turn-001"
    )
    record_observation(
        db, "creator", "vision", "Une luciole dans la nuit",
        "camera_snapshot", confidence=0.91,
        metadata={"scene": "jardin"}, event_id="vision-001",
    )
    record_affective_snapshot(
        db, "creator", {"joy": 62, "curiosity": 88},
        source="classic_chat", event_id="chat-turn-001",
    )
    db.commit()

    before = get_shared_brain_snapshot(db, "creator")
    before_context = format_shared_brain_context(before)
    assert before["statistics"]["totals"]["vocabulary"] == 2
    assert before["statistics"]["totals"]["sensory_observations"] == 1
    assert before["statistics"]["totals"]["decision_journal"] == 0
    assert "luciole" in before_context
    db.close()

    # A fresh connection models a process restart: no in-memory objects survive.
    reopened = open_db(path)
    try:
        after = get_shared_brain_snapshot(reopened, "creator")
        after_context = format_shared_brain_context(after)
        assert after["vocabulary"] == before["vocabulary"]
        assert after["sensory_observations"] == before["sensory_observations"]
        assert after["statistics"] == before["statistics"]
        assert after_context == before_context
        assert after["rules"]["observed_is_not_understood"] is True
        assert all(row["state"] == "heard" for row in after["vocabulary"])
    finally:
        reopened.close()


def test_pending_finalization_survives_close_reopen_and_can_be_retried(tmp_path):
    path = tmp_path / "chappie-outbox.sqlite3"
    db = open_db(path)
    initialize(db)
    assert enqueue_conversation_finalization(db, "creator", 17) is True
    assert enqueue_conversation_finalization(db, "creator", 17) is False
    db.commit()
    db.close()

    reopened = open_db(path)
    try:
        pending = list_pending_conversation_finalizations(reopened)
        assert len(pending) == 1
        assert pending[0]["user_id"] == "creator"
        assert pending[0]["through_conversation_id"] == 17
        mark_conversation_finalization(
            reopened, pending[0]["id"], error="temporary simulated failure"
        )
        reopened.commit()
    finally:
        reopened.close()

    retry = open_db(path)
    try:
        pending_again = list_pending_conversation_finalizations(retry)
        assert len(pending_again) == 1
        assert pending_again[0]["attempts"] == 1
        row = retry.execute(
            "SELECT status, last_error FROM conversation_finalization_outbox "
            "WHERE id=?", (pending_again[0]["id"],)
        ).fetchone()
        assert row["status"] == "pending"
        assert row["last_error"] == "temporary simulated failure"
        mark_conversation_finalization(retry, pending_again[0]["id"])
        retry.commit()
        assert list_pending_conversation_finalizations(retry) == []
    finally:
        retry.close()


def test_shared_brain_reconstruction_keeps_users_isolated(tmp_path):
    path = tmp_path / "chappie-users.sqlite3"
    db = open_db(path)
    initialize(db)
    record_heard_text(db, "creator", "luciole", event_id="same-event")
    record_heard_text(db, "other-user", "planète", event_id="same-event")
    db.commit()
    db.close()

    reopened = open_db(path)
    try:
        creator = get_shared_brain_snapshot(reopened, "creator")
        other = get_shared_brain_snapshot(reopened, "other-user")
        assert [row["word"] for row in creator["vocabulary"]] == ["luciole"]
        assert [row["word"] for row in other["vocabulary"]] == ["planète"]
    finally:
        reopened.close()


def test_restart_replay_does_not_duplicate_persisted_learning(tmp_path):
    path = tmp_path / "chappie-replay.sqlite3"
    db = open_db(path)
    initialize(db)
    first = record_heard_text(
        db, "creator", "luciole forêt", event_id="stable-event-42"
    )
    db.commit()
    db.close()

    reopened = open_db(path)
    try:
        replay = record_heard_text(
            reopened, "creator", "luciole forêt", event_id="stable-event-42"
        )
        reopened.commit()
        snapshot = get_shared_brain_snapshot(reopened, "creator")
        assert len(first) == 2
        assert replay == []
        assert snapshot["statistics"]["totals"]["vocabulary"] == 2
    finally:
        reopened.close()
