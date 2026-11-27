"""Crash-window regression test for durable conversation finalization."""
from __future__ import annotations

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from memory.conversation_outbox import list_pending_conversation_finalizations


def test_outbox_retry_after_summary_commit_does_not_duplicate_summary(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-summary-commit-retry.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database)
    server.init_db()

    # Build ten source messages and durable outbox markers without running
    # finalization, simulating a process that has not yet handled the jobs.
    monkeypatch.setattr(
        server, "finalize_conversation_turn",
        lambda _user_id: {"pending": 0, "completed": 0},
    )
    for index in range(5):
        server.save_conversation_turn(
            "creator",
            f"Message de reprise numéro {index}.",
            f"Réponse de reprise numéro {index}.",
        )

    original_mark = server.mark_conversation_finalization
    fail_once = {"remaining": 1}

    def fail_after_summary_commit(db, job_id, error=None):
        # The summary has already committed in consolidate_conversation.
        # Fail the first outbox completion write to model a process interruption
        # in the small window between those two durable operations.
        if error is None and fail_once["remaining"]:
            fail_once["remaining"] -= 1
            raise RuntimeError("simulated interruption after summary commit")
        return original_mark(db, job_id, error=error)

    monkeypatch.setattr(server, "mark_conversation_finalization", fail_after_summary_commit)
    first = server.finalize_conversation_turn("creator")
    assert first["pending"] > 0
    assert first["completed"] == 0

    with server.db_connection() as db:
        summary_rows = db.execute(
            "SELECT COUNT(*) FROM conversation_summaries WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
        summary_journal_rows = db.execute(
            "SELECT COUNT(*) FROM journal WHERE user_id=? AND kind='summary'",
            ("creator",),
        ).fetchone()[0]
        pending_after_interruption = list_pending_conversation_finalizations(
            db, user_id="creator"
        )
    assert summary_rows == 1
    assert summary_journal_rows == 1
    assert len(pending_after_interruption) == 5

    # A fresh retry sees the committed summary cursor, skips consolidation,
    # and only completes the still-pending outbox markers.
    monkeypatch.setattr(server, "mark_conversation_finalization", original_mark)
    second = server.finalize_conversation_turn("creator")
    assert second == {"pending": 0, "completed": 5}

    with server.db_connection() as db:
        summary_rows = db.execute(
            "SELECT COUNT(*) FROM conversation_summaries WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
        summary_journal_rows = db.execute(
            "SELECT COUNT(*) FROM journal WHERE user_id=? AND kind='summary'",
            ("creator",),
        ).fetchone()[0]
        pending_after_retry = list_pending_conversation_finalizations(
            db, user_id="creator"
        )
    assert summary_rows == 1
    assert summary_journal_rows == 1
    assert pending_after_retry == []
