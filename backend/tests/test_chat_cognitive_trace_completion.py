import asyncio

import pytest


def _prepare_isolated_server(monkeypatch, tmp_path):
    import server

    database_path = tmp_path / "chat-trace-completion.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-provider-key")
    server.init_db()
    monkeypatch.setattr(
        server,
        "retrieve_memories",
        lambda user_id, query="", limit=10: [{"confidence": 0.1}],
    )
    return server


def test_failed_chat_generation_does_not_persist_memory_doubt_trace(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    async def failing_provider(contents, user_id, query=""):
        raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(server, "call_gemini", failing_provider)

    with pytest.raises(RuntimeError, match="simulated provider failure"):
        asyncio.run(server.run_brain("creator", "zorbital"))

    with server.db_connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM cognitive_traces WHERE user_id=?",
            ("creator",),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id=?",
            ("creator",),
        ).fetchone()[0] == 0


def test_successful_chat_persists_memory_doubt_trace_after_conversation_save(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    async def successful_provider(contents, user_id, query=""):
        return {"parts": [{"text": "zorbital"}]}

    monkeypatch.setattr(server, "call_gemini", successful_provider)
    original_save = server.save_conversation_turn

    def verify_save_precedes_trace(user_id, message, reply, source="conversation"):
        with server.db_connection() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE user_id=?",
                (user_id,),
            ).fetchone()[0] == 0
        original_save(user_id, message, reply, source=source)

    monkeypatch.setattr(server, "save_conversation_turn", verify_save_precedes_trace)

    result = asyncio.run(server.run_brain("creator", "zorbital"))
    assert result["reply"] == "zorbital"

    with server.db_connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id=?",
            ("creator",),
        ).fetchone()[0] == 2
        traces = db.execute(
            "SELECT thought_type, context_summary FROM cognitive_traces WHERE user_id=?",
            ("creator",),
        ).fetchall()
        assert len(traces) == 1
        assert traces[0]["thought_type"] == "incertitude_contexte_memoire_chat"
        assert "zorbital" not in traces[0]["context_summary"]



def test_completed_conversations_trigger_bounded_automatic_metacognitive_audits(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    for index in range(1, 9):
        assert server.record_memory_relevance_doubt_trace(
            "creator", f"question-{index}", channel="chat"
        ) is True

        with server.db_connection() as db:
            trace_count = db.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE user_id=?",
                ("creator",),
            ).fetchone()[0]
            audit_count = db.execute(
                "SELECT COUNT(*) FROM metacognition_logs WHERE user_id=?",
                ("creator",),
            ).fetchone()[0]

        assert trace_count == index
        assert audit_count == index // 4

    with server.db_connection() as db:
        latest = db.execute(
            "SELECT trace_count, findings FROM metacognition_logs "
            "WHERE user_id=? ORDER BY id DESC LIMIT 1",
            ("creator",),
        ).fetchone()
        assert latest["trace_count"] == 8
        assert '"reasoning_quality_verified": false' in latest["findings"]

def test_automatic_metacognitive_audit_cadence_ignores_unrelated_traces(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    with server.db_connection() as db:
        for index in range(3):
            server.log_cognitive_trace(
                db,
                "creator",
                "general_reasoning",
                f"Unrelated trace {index}",
                "Recorded independently",
                0.8,
            )
        db.commit()

    for index in range(1, 5):
        assert server.record_memory_relevance_doubt_trace(
            "creator", f"question-{index}", channel="chat"
        ) is True

    with server.db_connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM cognitive_traces WHERE user_id=?",
            ("creator",),
        ).fetchone()[0] == 7
        audit = db.execute(
            "SELECT audit_type, trace_count, findings FROM metacognition_logs WHERE user_id=?",
            ("creator",),
        ).fetchone()
        assert audit["audit_type"] == "automatic_memory_context"
        assert audit["trace_count"] == 4
        assert '"thought_types_filter"' in audit["findings"]

def test_automatic_metacognitive_audit_reaches_shared_brain_context(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    for index in range(4):
        assert server.record_memory_relevance_doubt_trace(
            "creator", f"question-{index}", channel="chat"
        ) is True

    with server.db_connection() as db:
        snapshot = server.get_shared_brain_snapshot(db, "creator")
        context = server.format_shared_brain_context(snapshot)

    assert snapshot["snapshot_version"] == "35.0"
    assert len(snapshot["metacognitive_reviews"]) == 1
    assert "AUTO-ÉVALUATIONS" in context
    assert "reasoning_quality_verified" in context
    assert "Renforcer la vérification des informations" in context


def test_manual_metacognitive_audit_preserves_requested_filter_metadata(
    monkeypatch, tmp_path
):
    server = _prepare_isolated_server(monkeypatch, tmp_path)

    with server.db_connection() as db:
        server.log_cognitive_trace(
            db, "creator", "general_reasoning", "General trace", "Review", 0.8
        )
        server.log_cognitive_trace(
            db, "creator", "memory_doubt", "Memory trace", "Verify", 0.3
        )

        general = server.run_metacognitive_audit(db, "creator")
        filtered = server.run_metacognitive_audit(
            db, "creator", thought_types=["memory_doubt"]
        )
        db.commit()

    assert general["findings"]["thought_types_filter"] is None
    assert filtered["findings"]["thought_types_filter"] == ["memory_doubt"]
    assert filtered["trace_count"] == 1

