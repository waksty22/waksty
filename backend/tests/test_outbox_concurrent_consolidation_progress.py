"""Regression test for outbox progress when another worker wins consolidation."""
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


def test_outbox_finalization_accepts_cursor_inserted_by_concurrent_worker(
    tmp_path, monkeypatch
):
    database = tmp_path / "concurrent-outbox-progress.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database)
    server.init_db()

    with server.db_connection() as db:
        for index in range(12):
            cursor = db.execute(
                """
                INSERT INTO conversations(user_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "creator",
                    "user" if index % 2 == 0 else "assistant",
                    f"Message {index}",
                    f"2026-11-27T17:00:{index:02d}Z",
                ),
            )
        enqueue_conversation_finalization(db, "creator", int(cursor.lastrowid))
        db.commit()

    results = iter(
        (
            # Another worker inserted this summary after our stale cursor read.
            {"created": False, "summary": "Résumé du worker concurrent", "through_id": 10},
            {"created": True, "summary": "Résumé final", "through_id": 12},
        )
    )
    calls = []

    def concurrent_consolidation(user_id):
        calls.append(user_id)
        return next(results)

    monkeypatch.setattr(server, "consolidate_conversation", concurrent_consolidation)

    report = server.finalize_conversation_turn("creator")

    assert report == {"pending": 0, "completed": 1}
    assert calls == ["creator", "creator"]
    with server.db_connection() as db:
        assert list_pending_conversation_finalizations(
            db, user_id="creator"
        ) == []
