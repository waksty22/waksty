"""Crash-window regression test for durable conversation finalization."""
from __future__ import annotations

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from memory.conversation_outbox import (
    enqueue_conversation_finalization,
    list_pending_conversation_finalizations,
)


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

    # Seed ten source messages and their durable outbox markers directly in
    # one isolated transaction. This keeps the test focused on the recovery
    # boundary rather than the separate conversation-save path.
    with server.db_connection() as db:
        for index in range(5):
            for role, text in (
                ("user", f"Message de reprise numéro {index}."),
                ("assistant", f"Réponse de reprise numéro {index}."),
            ):
                cursor = db.execute(
                    """
                    INSERT INTO conversations(user_id, role, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("creator", role, text, f"2026-11-27T16:00:{index:02d}Z"),
                )
            enqueue_conversation_finalization(db, "creator", int(cursor.lastrowid))
        db.commit()

    with server.db_connection() as db:
        seeded_pending = list_pending_conversation_finalizations(
            db, user_id="creator"
        )
    assert len(seeded_pending) == 5

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


def test_outbox_uses_highest_summary_cursor_not_latest_insert_id(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-summary-cursor-order.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database)
    server.init_db()

    with server.db_connection() as db:
        for index in range(25):
            db.execute(
                """
                INSERT INTO conversations(user_id, role, content, created_at)
                VALUES ('creator', 'user', ?, ?)
                """,
                (f"Message {index}", f"2026-11-27T16:00:{index:02d}Z"),
            )
        # Simulate legacy/out-of-order rows: the highest durable cursor was
        # inserted first, while a lower cursor received the later row ID.
        db.execute(
            """
            INSERT INTO conversation_summaries(
                user_id, summary, through_conversation_id, created_at
            ) VALUES ('creator', 'Résumé au curseur 20', 20, '2026-11-27T16:01:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO conversation_summaries(
                user_id, summary, through_conversation_id, created_at
            ) VALUES ('creator', 'Ancien résumé au curseur 10', 10, '2026-11-27T16:02:00Z')
            """
        )
        enqueue_conversation_finalization(db, "creator", 25)
        db.commit()

    def unexpected_consolidation(_user_id):
        raise AssertionError("A valid cursor 20 must not trigger redundant consolidation")

    monkeypatch.setattr(server, "consolidate_conversation", unexpected_consolidation)
    result = server.finalize_conversation_turn("creator")

    assert result == {"pending": 0, "completed": 1}

def test_latest_autobiographical_summary_uses_highest_durable_cursor(
    tmp_path, monkeypatch
):
    database = tmp_path / "latest-summary-cursor.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database)
    server.init_db()

    with server.db_connection() as db:
        # The newer durable cursor is deliberately inserted first.
        db.execute(
            """
            INSERT INTO conversation_summaries(
                user_id, summary, through_conversation_id, created_at
            ) VALUES ('creator', 'Résumé au curseur 20', 20, '2026-11-27T16:01:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO conversation_summaries(
                user_id, summary, through_conversation_id, created_at
            ) VALUES ('creator', 'Ancien résumé au curseur 10', 10, '2026-11-27T16:02:00Z')
            """
        )
        db.commit()

    assert server.get_latest_summary("creator") == "Résumé au curseur 20"

