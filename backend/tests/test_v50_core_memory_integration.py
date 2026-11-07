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
