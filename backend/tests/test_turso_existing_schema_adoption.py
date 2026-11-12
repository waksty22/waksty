"""Safety tests for explicit adoption of an existing compatible Turso schema."""
from __future__ import annotations

import sqlite3

import pytest


CORE_COLUMNS = {
    "conversation_summaries": "id INTEGER, user_id TEXT, summary TEXT, through_conversation_id INTEGER, created_at TEXT",
    "conversations": "id INTEGER, user_id TEXT, role TEXT, content TEXT, created_at TEXT",
    "dreams": "id INTEGER, user_id TEXT, content TEXT, created_at TEXT",
    "emotional_state": "user_id TEXT, joy REAL, fear REAL, curiosity REAL, frustration REAL, sadness REAL, energy REAL, updated_at TEXT",
    "goal_steps": "id INTEGER, goal_id INTEGER, description TEXT, status TEXT, evidence TEXT, updated_at TEXT",
    "goals": "id INTEGER, user_id TEXT, title TEXT, status TEXT, progress REAL, created_at TEXT, updated_at TEXT",
    "journal": "id INTEGER PRIMARY KEY, user_id TEXT, entry TEXT, kind TEXT, created_at TEXT",
    "maintenance_state": "user_id TEXT, last_active_at TEXT, last_dream_at TEXT, updated_at TEXT",
    "memories": "id INTEGER, user_id TEXT, category TEXT, content TEXT, importance INTEGER, tags TEXT, access_count INTEGER, created_at TEXT, updated_at TEXT",
    "mood_events": "id INTEGER, user_id TEXT, event TEXT, valence REAL, arousal REAL, created_at TEXT",
    "relationships": "user_id TEXT PRIMARY KEY, trust REAL, affection REAL, dependence REAL, updated_at TEXT",
    "skills": "id INTEGER, user_id TEXT, skill_name TEXT, level REAL, evidence TEXT, updated_at TEXT",
    "voice_profiles": "id INTEGER PRIMARY KEY, user_id TEXT, profile_name TEXT, embedding_json TEXT, created_at TEXT, updated_at TEXT",
}


def _create_compatible_schema(path):
    db = sqlite3.connect(path)
    try:
        for table, columns in CORE_COLUMNS.items():
            db.execute(f'CREATE TABLE "{table}" ({columns})')
        db.execute(
            "INSERT INTO journal VALUES (1, 'creator', 'preserve this row', 'note', 'now')"
        )
        db.execute(
            "INSERT INTO relationships VALUES ('creator', 0.8, 0.7, 0.1, 'now')"
        )
        db.execute(
            "INSERT INTO voice_profiles VALUES (1, 'creator', 'stable', '{}', 'now', 'now')"
        )
        db.commit()
    finally:
        db.close()


def test_existing_schema_adoption_is_opt_in_and_preserves_existing_rows(
    monkeypatch, tmp_path
):
    import server

    database = tmp_path / "existing-turso.sqlite3"
    _create_compatible_schema(database)
    monkeypatch.setattr(
        server, "db_connection", lambda: sqlite3.connect(database)
    )
    monkeypatch.setattr(
        server,
        "_remote_turso_migration_completed",
        lambda **kwargs: False,
    )
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "turso")
    monkeypatch.setenv("CHAPPIE_TURSO_CUTOVER_READY", "1")
    monkeypatch.setenv("CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA", "1")
    monkeypatch.delenv("CHAPPIE_TURSO_FRESH_START", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")

    server.init_db()

    check = sqlite3.connect(database)
    try:
        assert check.execute(
            "SELECT entry FROM journal WHERE id=1"
        ).fetchone() == ("preserve this row",)
        assert check.execute(
            "SELECT trust FROM relationships WHERE user_id='creator'"
        ).fetchone() == (0.8,)
        assert check.execute(
            "SELECT profile_name FROM voice_profiles WHERE id=1"
        ).fetchone() == ("stable",)
        assert check.execute(
            "SELECT migration_key, status FROM chappie_storage_migrations"
        ).fetchall() == [("turso-existing-schema-adoption-v1", "completed")]
        assert check.execute(
            "SELECT COUNT(*) FROM chappie_storage_migrations "
            "WHERE migration_key='sqlite-to-turso-v50.65'"
        ).fetchone()[0] == 0
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='memories_v19'"
        ).fetchone()[0] == 1
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='place_memories'"
        ).fetchone()[0] == 1
    finally:
        check.close()


def test_existing_schema_adoption_rejects_incomplete_schema(monkeypatch, tmp_path):
    import server

    database = tmp_path / "incomplete-turso.sqlite3"
    check = sqlite3.connect(database)
    check.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY)")
    check.commit()
    check.close()
    monkeypatch.setattr(
        server, "db_connection", lambda: sqlite3.connect(database)
    )

    assert server._turso_existing_schema_compatible() is False


def test_existing_schema_adoption_marker_is_accepted_only_when_enabled(
    monkeypatch,
):
    import sys
    import types
    import server

    remote = sqlite3.connect(":memory:")
    remote.execute(
        "CREATE TABLE chappie_storage_migrations "
        "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL)"
    )
    remote.execute(
        "INSERT INTO chappie_storage_migrations VALUES "
        "('turso-existing-schema-adoption-v1', 'completed')"
    )
    remote.commit()

    class FakeLibsqlConnection:
        def execute(self, *args, **kwargs):
            return remote.execute(*args, **kwargs)

        def close(self):
            return None

    monkeypatch.setitem(
        sys.modules, "libsql",
        types.SimpleNamespace(connect=lambda **kwargs: FakeLibsqlConnection()),
    )
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")

    try:
        assert server._remote_turso_migration_completed(
            allow_existing_schema_adoption=True
        ) is True
        with pytest.raises(RuntimeError, match="migration non confirmée"):
            server._remote_turso_migration_completed()
    finally:
        remote.close()
