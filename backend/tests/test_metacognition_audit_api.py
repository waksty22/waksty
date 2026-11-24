"""API regression tests for the metacognitive audit route."""
from __future__ import annotations

import asyncio


def test_cognition_audit_route_uses_database_and_persists_audit(
    monkeypatch, tmp_path
):
    import server

    database_path = tmp_path / "metacognition-audit.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_SQLITE_PATH", str(database_path))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    server.init_db()
    with server.db_connection() as db:
        server.log_cognitive_trace(
            db,
            "creator",
            "test_reasoning",
            "Trace de test pour vérifier l'audit métacognitif.",
            "verify",
            0.8,
        )
        db.commit()

    response = asyncio.run(server.api_cognition_audit(auth="creator"))

    assert response["audit"]["user_id"] == "creator"
    assert response["audit"]["trace_count"] == 1
    assert response["audit"]["findings"]["reasoning_quality_verified"] is False

    with server.db_connection() as db:
        rows = db.execute(
            "SELECT user_id, trace_count FROM metacognition_logs"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["user_id"] == "creator"
        assert rows[0]["trace_count"] == 1
