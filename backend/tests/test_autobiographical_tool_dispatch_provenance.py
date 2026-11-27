"""Autobiographical search tool must preserve source provenance and user isolation."""
from __future__ import annotations

import server


def test_autobiographical_search_tool_returns_only_users_source_grounded_events(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "autobiographical-tool-dispatch.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    server.init_db()

    timestamp = "2026-11-27T10:00:00Z"
    with server.db_connection() as db:
        db.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("creator", "user", "Mon horloge astronomique rouge est dans le salon.", timestamp),
        )
        db.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("creator", "assistant", "Je retiens ce que tu viens de me dire.", timestamp),
        )
        db.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("another-user", "user", "Mon horloge astronomique rouge est dans une pièce privée.", timestamp),
        )
        db.commit()

    result = server.execute_tool(
        "search_autobiographical_events",
        {"query": "horloge astronomique rouge"},
        "creator",
    )

    assert result["grounded_in_source_messages"] is True
    assert result["dialogue_links_are_context_not_confirmation"] is True
    events = result["events"]
    assert events
    assert any(
        item["source_conversation_id"] == 1
        and item["actor"] == "user"
        and "salon" in item["content"]
        for item in events
    )
    assert any(
        item["source_conversation_id"] == 2
        and item["actor"] == "assistant"
        and item["dialogue_context"] is True
        and item["relevance_score"] == 0.0
        for item in events
    )
    assert all("pièce privée" not in item["content"] for item in events)
    assert all(item["source_conversation_id"] != 3 for item in events)
