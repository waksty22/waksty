"""Cross-module V50 smoke test against an isolated local libSQL database.

No remote Turso endpoint, production database, or real location data is used.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from memory.episodic_memory import (
    init_memory_tables,
    save_episodic_memory,
    search_episodic_memories,
)
from memory.autobiographical import (
    init_autobiographical_tables,
    sync_autobiographical_events,
)
from world.spatial_memory import (
    init_spatial_tables,
    start_location_session,
    record_location,
)
from world.world_model import init_world_tables, upsert_world_entity


def test_core_memory_world_modules_share_one_libsql_connection():
    native = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(native)
    try:
        # Minimal conversation source schema used by the autobiographical index.
        db.execute("""
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("owner", "user", "J'apprends à reconnaître les lieux.", "2026-11-07T00:00:00Z"),
        )

        init_memory_tables(db)
        init_autobiographical_tables(db)
        init_spatial_tables(db)
        init_world_tables(db)

        saved = save_episodic_memory(
            db,
            user_id="owner",
            content="Chappie apprend à reconnaître les lieux.",
            category="learning",
            importance=4,
            source_type="taught",
            confidence=0.9,
            tags=["lieux", "apprentissage"],
        )
        assert saved["content"] == "Chappie apprend à reconnaître les lieux."
        found = search_episodic_memories(db, "owner", "reconnaître")
        assert len(found) == 1
        assert found[0]["importance"] == 4

        indexed = sync_autobiographical_events(db, "owner")
        assert indexed["inserted"] == 1

        session = start_location_session(
            db, user_id="owner", consented=True, device_label="test-device"
        )
        location = record_location(
            db,
            user_id="owner",
            session_id=session["session_id"],
            latitude=48.0,
            longitude=-3.0,
            accuracy_m=12.0,
            recorded_at="2026-11-07T00:01:00Z",
        )
        assert location["stored"] is True

        entity = upsert_world_entity(
            db,
            user_id="owner",
            entity_id="place:test-square",
            entity_type="place",
            properties={"label": "Place de test"},
            source_type="taught",
            confidence=0.95,
        )
        assert entity["id"] == "place:test-square"

        # All modules use the same adapter and retain per-user boundaries.
        assert db.execute(
            "SELECT COUNT(*) FROM spatial_visits WHERE user_id=?",
            ("another-user",),
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_shared_brain_reuses_chat_memory_after_connection_restart(tmp_path):
    """The persisted memory is visible to both chat and Live context builders."""
    from cognition.shared_brain import (
        get_shared_brain_snapshot,
        format_shared_brain_context,
    )
    from memory.knowledge_acquisition import (
        retrieve_acquired_knowledge,
        format_acquired_knowledge_context,
    )
    from storage.connection_factory import StorageSettings, open_storage_connection

    database_path = tmp_path / "shared-brain.sqlite3"
    settings = StorageSettings(
        backend="sqlite",
        sqlite_path=str(database_path),
    )
    taught_fact = "Le compagnon apprend que le mot chaussure désigne un objet porté aux pieds."

    first = open_storage_connection(settings)
    try:
        init_memory_tables(first)
        saved = save_episodic_memory(
            first,
            user_id="owner",
            content=taught_fact,
            category="vocabulary",
            importance=5,
            source_type="taught",
            confidence=0.95,
            tags=["chaussure", "objet"],
        )
        assert saved["saved"] is True
        first.commit()
    finally:
        first.close()

    # Simulate an application restart: a completely new connection reads the
    # same persisted row through both context builders used by chat and Live.
    second = open_storage_connection(settings)
    try:
        chat_snapshot = get_shared_brain_snapshot(second, "owner", limit=20)
        live_snapshot = get_shared_brain_snapshot(second, "owner", limit=20)
        assert chat_snapshot == live_snapshot
        assert any(
            item.get("content") == taught_fact
            for item in chat_snapshot["memories"]
        )

        chat_context = format_shared_brain_context(chat_snapshot)
        live_context = format_shared_brain_context(live_snapshot)
        assert chat_context == live_context
        assert taught_fact in chat_context

        acquired = retrieve_acquired_knowledge(
            second, "owner", query="chaussure", limit=10
        )
        acquired_context = format_acquired_knowledge_context(acquired)
        assert taught_fact in acquired_context
        assert acquired["user_scoped"] is True
        assert acquired["read_only"] is True

        # The same memory must not leak into another user's context.
        other_user = get_shared_brain_snapshot(second, "another-user", limit=20)
        assert not any(
            item.get("content") == taught_fact
            for item in other_user["memories"]
        )
    finally:
        second.close()


def test_written_chat_and_gemini_live_use_the_same_persisted_identity_context():
    """Guard the two production entrypoints against memory-context drift."""
    import inspect
    import server

    chat_source = inspect.getsource(server.call_gemini)
    live_source = inspect.getsource(server.websocket_endpoint)
    identity_source = inspect.getsource(server.get_identity_prompt)

    # Both modalities must build their system prompt through the same function.
    assert "get_identity_prompt(user_id, query=query)" in chat_source
    assert "get_identity_prompt(user_id)" in live_source

    # That shared prompt must read durable autobiographical and shared-brain
    # state, not depend on a process-local conversation buffer.
    assert "sync_autobiographical_events" in identity_source
    assert "list_autobiographical_events" in identity_source
    assert "get_shared_brain_snapshot" in identity_source
    assert "format_shared_brain_context" in identity_source
    assert "retrieve_acquired_knowledge" in identity_source
    assert "format_acquired_knowledge_context" in identity_source

    # Both entrypoints must feed confirmed user text into the same durable
    # vocabulary table, while keeping lexical exposure distinct from mastery.
    chat_brain_source = inspect.getsource(server.run_brain)
    assert "record_heard_text(" in chat_brain_source
    assert "Message écrit reçu par le chat classique" in chat_brain_source
    assert "record_heard_text(" in live_source
    assert "Transcription confirmée par Gemini Live" in live_source
    assert "record_explicit_word_teaching(" in chat_brain_source
    assert "record_explicit_word_teaching(" in live_source



def test_memory_server_entrypoints_reject_coercion_before_storage():
    import inspect
    import server

    remember_source = inspect.getsource(server.remember)
    retrieve_source = inspect.getsource(server.retrieve_memories)

    assert "not isinstance(content, str)" in remember_source
    assert "not isinstance(source_type, str)" in remember_source
    assert "isinstance(importance, bool) or not isinstance(importance, int)" in remember_source
    assert "not isinstance(confidence, (int, float))" in remember_source
    assert "any(not isinstance(tag, str) for tag in tags)" in remember_source
    assert "int(importance)" not in remember_source
    assert "numeric_confidence = float(confidence)" in remember_source
    assert "math.isfinite(numeric_confidence)" in remember_source
    assert "not isinstance(query, str)" in retrieve_source
    assert "isinstance(limit, bool) or not isinstance(limit, int)" in retrieve_source
    assert "int(limit)" not in retrieve_source
