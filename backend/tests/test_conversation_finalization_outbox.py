"""Durable conversation finalization outbox regression tests."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from memory.conversation_outbox import (
    enqueue_conversation_finalization,
    init_conversation_finalization_outbox,
    list_pending_conversation_finalizations,
)


def _isolate_database(monkeypatch, path: Path) -> None:
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(path.parent))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", path)
    server.init_db()


def test_failed_consolidation_survives_connection_reopen_and_is_recovered(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-recovery.sqlite3"
    _isolate_database(monkeypatch, database)
    real_consolidate = server.consolidate_conversation

    def fail_consolidation(_user_id: str):
        raise RuntimeError("temporary consolidation failure")

    monkeypatch.setattr(server, "consolidate_conversation", fail_consolidation)
    for index in range(5):
        server.save_conversation_turn(
            "creator",
            f"Message de test numéro {index}.",
            f"Réponse de test numéro {index}.",
        )

    # A fresh connection observes the durable pending job and its failed attempt.
    with server.db_connection() as db:
        pending = list_pending_conversation_finalizations(db)
        row = db.execute(
            "SELECT attempts, status, last_error FROM conversation_finalization_outbox "
            "WHERE status='pending' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert len(pending) == 1
    assert row["attempts"] == 1
    assert row["status"] == "pending"
    assert row["last_error"] == "temporary consolidation failure"

    monkeypatch.setattr(server, "consolidate_conversation", real_consolidate)
    report = server.recover_pending_conversation_finalizations()
    assert report == {
        "users_checked": 1,
        "jobs_completed": 1,
        "jobs_still_pending": 0,
    }
    with server.db_connection() as db:
        assert list_pending_conversation_finalizations(db) == []
        summary = db.execute(
            "SELECT through_conversation_id FROM conversation_summaries "
            "WHERE user_id=? ORDER BY id DESC LIMIT 1",
            ("creator",),
        ).fetchone()
        completed = db.execute(
            "SELECT status, attempts, completed_at FROM conversation_finalization_outbox "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert summary["through_conversation_id"] == 10
    assert completed["status"] == "completed"
    assert completed["attempts"] == 2
    assert completed["completed_at"]


def test_conversation_and_outbox_marker_roll_back_together(tmp_path, monkeypatch):
    database = tmp_path / "outbox-atomicity.sqlite3"
    _isolate_database(monkeypatch, database)
    with server.db_connection() as db:
        init_conversation_finalization_outbox(db)
        db.commit()

    original_enqueue = server.enqueue_conversation_finalization

    def enqueue_then_fail(db, user_id, through_id):
        original_enqueue(db, user_id, through_id)
        raise RuntimeError("injected failure after outbox insert")

    monkeypatch.setattr(server, "enqueue_conversation_finalization", enqueue_then_fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        server.save_conversation_turn(
            "creator", "Message atomique.", "Réponse atomique."
        )

    with server.db_connection() as db:
        conversation_count = db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
        journal_count = db.execute(
            "SELECT COUNT(*) FROM journal WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
        outbox_count = db.execute(
            "SELECT COUNT(*) FROM conversation_finalization_outbox WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
    assert conversation_count == 0
    assert journal_count == 0
    assert outbox_count == 0


def test_outbox_enqueue_is_idempotent_for_user_and_cursor(tmp_path):
    database = tmp_path / "outbox-idempotence.sqlite3"
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    try:
        init_conversation_finalization_outbox(db)
        assert enqueue_conversation_finalization(db, "creator", 42) is True
        assert enqueue_conversation_finalization(db, "creator", 42) is False
        assert enqueue_conversation_finalization(db, "another-user", 42) is True
        db.commit()
        rows = db.execute(
            "SELECT user_id, through_conversation_id FROM conversation_finalization_outbox "
            "ORDER BY user_id"
        ).fetchall()
        assert [(row["user_id"], row["through_conversation_id"]) for row in rows] == [
            ("another-user", 42),
            ("creator", 42),
        ]
    finally:
        db.close()


def test_outbox_works_with_real_local_libsql_adapter():
    libsql = pytest.importorskip("libsql")
    from storage.libsql_adapter import adapt_libsql_connection

    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        init_conversation_finalization_outbox(db)
        assert enqueue_conversation_finalization(db, "creator", 17) is True
        pending = list_pending_conversation_finalizations(db)
        assert pending == [{
            "id": 1,
            "user_id": "creator",
            "through_conversation_id": 17,
            "attempts": 0,
        }]
        db.commit()
    finally:
        db.close()


def test_recovery_drains_more_than_one_consolidation_page(tmp_path, monkeypatch):
    database = tmp_path / "outbox-multipage.sqlite3"
    _isolate_database(monkeypatch, database)
    real_consolidate = server.consolidate_conversation

    def fail_consolidation(_user_id: str):
        raise RuntimeError("temporary offline consolidation")

    monkeypatch.setattr(server, "consolidate_conversation", fail_consolidation)
    for index in range(45):
        server.save_conversation_turn(
            "creator", f"Message long backlog {index}.",
            f"Réponse long backlog {index}.",
        )

    with server.db_connection() as db:
        pending_before = list_pending_conversation_finalizations(db)
    assert pending_before

    monkeypatch.setattr(server, "consolidate_conversation", real_consolidate)
    report = server.recover_pending_conversation_finalizations()
    assert report["users_checked"] == 1
    assert report["jobs_completed"] == len(pending_before)
    assert report["jobs_still_pending"] == 0

    with server.db_connection() as db:
        summary = db.execute(
            "SELECT through_conversation_id FROM conversation_summaries "
            "WHERE user_id=? ORDER BY id DESC LIMIT 1", ("creator",)
        ).fetchone()
        pending_after = list_pending_conversation_finalizations(db)
    assert summary["through_conversation_id"] == 90
    assert pending_after == []


def test_user_finalization_is_not_starved_by_other_users_pending_jobs(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-user-scope.sqlite3"
    _isolate_database(monkeypatch, database)
    with server.db_connection() as db:
        for index in range(500):
            enqueue_conversation_finalization(db, f"other-user-{index}", index + 1)
        enqueue_conversation_finalization(db, "creator", 1)
        db.commit()

    report = server.finalize_conversation_turn("creator")
    assert report == {"pending": 0, "completed": 1}

    with server.db_connection() as db:
        creator_jobs = list_pending_conversation_finalizations(
            db, user_id="creator"
        )
        other_jobs = list_pending_conversation_finalizations(db, limit=500)
    assert creator_jobs == []
    assert len(other_jobs) == 500


def test_startup_recovery_scans_all_pending_jobs_in_bounded_pages(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-startup-pagination.sqlite3"
    _isolate_database(monkeypatch, database)
    with server.db_connection() as db:
        for index in range(501):
            enqueue_conversation_finalization(db, "creator", index + 1)
        db.commit()

    monkeypatch.setattr(server, "valid_user", lambda user_id: user_id)
    calls = []

    def complete_page(user_id):
        calls.append(user_id)
        return {"pending": 0, "completed": 500 if len(calls) == 1 else 1}

    monkeypatch.setattr(server, "finalize_conversation_turn", complete_page)
    report = server.recover_pending_conversation_finalizations()

    assert calls == ["creator", "creator"]
    assert report == {
        "users_checked": 1,
        "jobs_completed": 501,
        "jobs_still_pending": 0,
    }


def test_outbox_pagination_cursor_is_validated(tmp_path):
    database = tmp_path / "outbox-cursor-validation.sqlite3"
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    try:
        init_conversation_finalization_outbox(db)
        for invalid in (-1, True, "2"):
            with pytest.raises(ValueError, match="cursor"):
                list_pending_conversation_finalizations(db, after_id=invalid)
    finally:
        db.close()


def test_new_turn_is_indexed_immediately_while_old_autobiographical_backlog_remains(
    tmp_path, monkeypatch
):
    database = tmp_path / "outbox-fresh-autobiography.sqlite3"
    _isolate_database(monkeypatch, database)
    with server.db_connection() as db:
        db.executemany(
            """
            INSERT INTO conversations(user_id, role, content, created_at)
            VALUES ('creator', 'user', ?, '2026-01-01T10:00:00Z')
            """,
            [(f"Ancien échange en attente numéro {index}",) for index in range(500)],
        )
        db.commit()

    # Keep this test focused on source indexing, not summary consolidation.
    monkeypatch.setattr(
        server, "finalize_conversation_turn",
        lambda _user_id: {"pending": 0, "completed": 0},
    )
    server.save_conversation_turn(
        "creator",
        "Je viens de montrer une nouvelle boussole.",
        "Je retiens cette nouvelle boussole.",
    )

    with server.db_connection() as db:
        indexed = db.execute(
            """
            SELECT source_conversation_id, actor, content
            FROM autobiographical_events
            WHERE user_id='creator'
            ORDER BY source_conversation_id
            """
        ).fetchall()

    assert [(row["actor"], row["content"]) for row in indexed] == [
        ("user", "Je viens de montrer une nouvelle boussole."),
        ("assistant", "Je retiens cette nouvelle boussole."),
    ]
    assert [row["source_conversation_id"] for row in indexed] == [501, 502]



@pytest.mark.parametrize("bad_user", [None, 123, True, "", " " , "x" * 129])
@pytest.mark.parametrize("bad_cursor", [True, False, 1.5, "7", 0, -1])
def test_outbox_enqueue_rejects_coerced_user_and_cursor_without_writing(
    bad_user, bad_cursor
):
    db = sqlite3.connect(":memory:")
    with pytest.raises(ValueError):
        enqueue_conversation_finalization(db, bad_user, bad_cursor)
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='conversation_finalization_outbox'"
    ).fetchone() is None
    db.close()


@pytest.mark.parametrize("bad_limit", [True, False, 1.5, "10", None])
def test_outbox_list_rejects_coerced_limits(bad_limit):
    db = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="limit"):
        list_pending_conversation_finalizations(db, limit=bad_limit)
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='conversation_finalization_outbox'"
    ).fetchone() is None
    db.close()


def test_outbox_mark_rejects_coerced_or_invalid_job_ids():
    from memory.conversation_outbox import mark_conversation_finalization

    db = sqlite3.connect(":memory:")
    init_conversation_finalization_outbox(db)
    for invalid in (True, False, 1.5, "1", 0, -1):
        with pytest.raises(ValueError, match="identifier"):
            mark_conversation_finalization(db, invalid)
    assert db.execute(
        "SELECT COUNT(*) FROM conversation_finalization_outbox"
    ).fetchone()[0] == 0
    db.close()
