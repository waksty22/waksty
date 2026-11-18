import sqlite3

import pytest

from storage.schema_migration import apply_migration_plan, build_migration_plan


def _databases(*, target_unique=False):
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_events_user
            ON events(user_id, id DESC);
        INSERT INTO events(user_id, created_at)
            VALUES ('creator', '2026-01-01');
    """)
    unique = "UNIQUE " if target_unique else ""
    target.executescript(f"""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE {unique}INDEX idx_events_user
            ON events(user_id);
        INSERT INTO events(user_id, created_at)
            VALUES ('creator', '2026-01-01');
    """)
    return source, target


def test_non_unique_index_drift_is_planned_and_repaired_transactionally():
    source, target = _databases()
    try:
        before = target.execute(
            "SELECT id, user_id, created_at FROM events"
        ).fetchall()

        plan = build_migration_plan(source, target)

        assert plan["ready"], plan["blockers"]
        assert [item["kind"] for item in plan["statements"]] == [
            "drop_index",
            "create_index",
        ]
        assert apply_migration_plan(target, plan)["applied"] is False
        assert target.execute(
            "SELECT id, user_id, created_at FROM events"
        ).fetchall() == before

        applied = apply_migration_plan(target, plan, apply=True)
        assert applied["applied"] is True
        assert applied["executed_count"] == 2
        assert target.execute(
            "SELECT id, user_id, created_at FROM events"
        ).fetchall() == before

        index_columns = target.execute(
            "PRAGMA index_info(idx_events_user)"
        ).fetchall()
        assert [row[2] for row in index_columns] == ["user_id", "id"]

        second = build_migration_plan(source, target)
        assert second["ready"], second["blockers"]
        assert second["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()


def test_unique_index_drift_remains_blocked():
    source, target = _databases(target_unique=True)
    try:
        plan = build_migration_plan(source, target)
        assert not plan["ready"]
        assert any("UNIQUE" in item for item in plan["blockers"])
        with pytest.raises(ValueError):
            apply_migration_plan(target, plan, apply=True)
    finally:
        source.close()
        target.close()


def test_index_replacement_rolls_back_if_recreation_fails():
    source, target = _databases()
    try:
        plan = build_migration_plan(source, target)
        broken = {
            **plan,
            "statements": [
                plan["statements"][0],
                {
                    "kind": "create_index",
                    "object": "broken_index",
                    "sql": "CREATE INDEX broken_index ON events(no_such_column)",
                },
            ],
        }
        with pytest.raises(sqlite3.OperationalError):
            apply_migration_plan(target, broken, apply=True)

        index_columns = target.execute(
            "PRAGMA index_info(idx_events_user)"
        ).fetchall()
        assert [row[2] for row in index_columns] == ["user_id"]
    finally:
        source.close()
        target.close()
