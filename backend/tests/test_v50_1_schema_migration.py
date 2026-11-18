import sqlite3

import pytest

from storage.schema_migration import (
    apply_migration_plan,
    build_migration_plan,
)


def _source():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0,
            xp REAL NOT NULL DEFAULT 0.0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_people_name ON people(name);
        INSERT INTO people(name) VALUES ('preserve-me');
        INSERT INTO skills(user_id, skill_name, updated_at)
        VALUES ('creator', 'language', 'now');
    """)
    return db


def _target_without_new_schema():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        INSERT INTO skills(user_id, skill_name, updated_at)
        VALUES ('creator', 'existing-skill', 'before-migration');
    """)
    return db


def test_plan_is_read_only_and_includes_missing_table_index_and_xp():
    source = _source()
    target = _target_without_new_schema()
    try:
        before = target.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        plan = build_migration_plan(source, target)
        after = target.execute("SELECT COUNT(*) FROM skills").fetchone()[0]

        assert plan["ready"]
        assert plan["missing_tables"] == ["people"]
        assert any(item["object"] == "skills.xp" for item in plan["statements"])
        assert any(item["object"] == "idx_people_name" for item in plan["statements"])
        assert before == after == 1
        assert apply_migration_plan(target, plan)["applied"] is False
        assert "people" not in {
            row[0] for row in target.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        source.close()
        target.close()


def test_apply_is_additive_and_preserves_existing_rows():
    source = _source()
    target = _target_without_new_schema()
    try:
        plan = build_migration_plan(source, target)
        result = apply_migration_plan(target, plan, apply=True)

        assert result["applied"]
        assert target.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0
        assert target.execute(
            "SELECT user_id, skill_name FROM skills"
        ).fetchone() == ("creator", "existing-skill")
        assert "xp" in {
            row[1] for row in target.execute("PRAGMA table_info(skills)")
        }
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='index' AND name='idx_people_name'"
        ).fetchone()[0] == 1

        # A second planning pass is a no-op: the migration is idempotent.
        rerun = build_migration_plan(source, target)
        assert rerun["ready"], rerun["blockers"]
        assert rerun["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()


def test_unknown_missing_column_blocks_apply():
    source = _source()
    target = sqlite3.connect(":memory:")
    target.execute("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)
    try:
        plan = build_migration_plan(
            source,
            target,
            additive_columns={"skills": {}},
        )
        assert not plan["ready"]
        with pytest.raises(ValueError):
            apply_migration_plan(target, plan, apply=True)
    finally:
        source.close()
        target.close()



def test_failed_apply_rolls_back_all_schema_changes():
    target = sqlite3.connect(":memory:")
    plan = {
        "ready": True,
        "planned_statement_count": 2,
        "statements": [
            {
                "kind": "create_table",
                "object": "temporary_table",
                "sql": "CREATE TABLE temporary_table (id INTEGER PRIMARY KEY)",
            },
            {
                "kind": "create_table",
                "object": "broken_table",
                "sql": "CREATE TABLE broken_table (",
            },
        ],
    }
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migration_plan(target, plan, apply=True)
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='temporary_table'"
        ).fetchone()[0] == 0
    finally:
        target.close()


@pytest.mark.parametrize(
    "source_sql, target_sql",
    [
        (
            "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
            "skill_name TEXT NOT NULL, level REAL NOT NULL CHECK(level >= 0), "
            "xp REAL NOT NULL DEFAULT 0.0, evidence TEXT NOT NULL DEFAULT '', "
            "updated_at TEXT NOT NULL)",
            "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
            "skill_name TEXT NOT NULL, level REAL NOT NULL, "
            "evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)",
        ),
        (
            "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL UNIQUE, "
            "skill_name TEXT NOT NULL, level REAL NOT NULL, "
            "xp REAL NOT NULL DEFAULT 0.0, evidence TEXT NOT NULL DEFAULT '', "
            "updated_at TEXT NOT NULL)",
            "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
            "skill_name TEXT NOT NULL, level REAL NOT NULL, "
            "evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)",
        ),
    ],
)
def test_unmatched_table_constraints_block_migration(source_sql, target_sql):
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    try:
        source.execute(source_sql)
        target.execute(target_sql)
        plan = build_migration_plan(source, target)
        assert not plan["ready"]
        assert any("CHECK" in item or "UNIQUE" in item for item in plan["blockers"])
        with pytest.raises(ValueError):
            apply_migration_plan(target, plan, apply=True)
    finally:
        source.close()
        target.close()
