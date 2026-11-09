import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.data_migration import (
    build_data_migration_plan,
    migrate_sqlite_rows_to_turso,
)


def _databases(target_parent_label="same"):
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("PRAGMA foreign_keys=ON")
    target.execute("PRAGMA foreign_keys=ON")

    source.executescript(
        """
        CREATE TABLE parent (
            id INTEGER PRIMARY KEY,
            label TEXT NOT NULL
        );
        CREATE TABLE child (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL REFERENCES parent(id),
            note TEXT NOT NULL
        );
        CREATE INDEX idx_child_parent ON child(parent_id);
        INSERT INTO parent(id, label) VALUES (1, 'same'), (2, 'new');
        INSERT INTO child(id, parent_id, note) VALUES (10, 2, 'souvenir');
        """
    )
    target.executescript(
        f"""
        CREATE TABLE parent (
            id INTEGER PRIMARY KEY,
            label TEXT NOT NULL
        );
        INSERT INTO parent(id, label) VALUES (1, '{target_parent_label}'), (99, 'target-only');
        """
    )
    source.commit()
    target.commit()
    return source, target


def test_data_migration_preview_is_read_only_and_reports_no_content():
    source, target = _databases()
    try:
        plan = build_data_migration_plan(source, target)
        assert plan["ready"] is True
        assert plan["read_only"] is True
        assert plan["data_contents_exposed"] is False
        assert plan["schema_plan"]["planned_statement_count"] >= 2
        assert target.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 2
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='child'"
        ).fetchone()[0] == 0
    finally:
        source.close()
        target.close()


def test_data_migration_copies_rows_preserves_target_and_is_idempotent():
    source, target = _databases()
    try:
        first = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert first["applied"] is True
        assert first["inserted_rows"] == 2
        assert first["already_present_rows"] == 1
        assert target.execute("SELECT label FROM parent WHERE id=99").fetchone()[0] == "target-only"
        assert target.execute("SELECT note FROM child WHERE id=10").fetchone()[0] == "souvenir"
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []

        second = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert second["applied"] is True
        assert second["inserted_rows"] == 0
        assert second["already_present_rows"] == 3
    finally:
        source.close()
        target.close()


def test_conflicting_primary_key_aborts_and_rolls_back_all_changes():
    source, target = _databases(target_parent_label="different")
    try:
        with pytest.raises(ValueError, match="Collision de clé"):
            migrate_sqlite_rows_to_turso(source, target, apply=True)

        assert target.execute("SELECT label FROM parent WHERE id=1").fetchone()[0] == "different"
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='child'"
        ).fetchone()[0] == 0
        assert target.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 2
    finally:
        source.close()
        target.close()



def test_data_migration_blocks_existing_table_constraint_drift():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    try:
        source.execute(
            "CREATE TABLE guarded (id INTEGER PRIMARY KEY, label TEXT NOT NULL CHECK(length(label) > 0))"
        )
        target.execute(
            "CREATE TABLE guarded (id INTEGER PRIMARY KEY, label TEXT NOT NULL CHECK(length(label) > 1))"
        )
        source.commit()
        target.commit()

        plan = build_data_migration_plan(source, target)

        assert plan["ready"] is False
        assert plan["read_only"] is True
        assert plan["blockers"]
        assert target.execute(
            "SELECT sql FROM sqlite_master WHERE name='guarded'"
        ).fetchone()[0].endswith("CHECK(length(label) > 1))")
    finally:
        source.close()
        target.close()

def test_skills_xp_column_removal_matches_legacy_table_sql():
    from storage.data_migration import _remove_column_from_create_sql

    source_sql = (
        "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
        "skill_name TEXT NOT NULL, level REAL NOT NULL DEFAULT 0.0, "
        "xp REAL NOT NULL DEFAULT 0.0, evidence TEXT NOT NULL DEFAULT '', "
        "updated_at TEXT NOT NULL, UNIQUE(user_id, skill_name))"
    )
    target_sql = (
        "CREATE TABLE skills (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, "
        "skill_name TEXT NOT NULL, level REAL NOT NULL DEFAULT 0.0, "
        "evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, "
        "UNIQUE(user_id, skill_name))"
    )

    assert _remove_column_from_create_sql(source_sql, "xp") == " ".join(target_sql.split()).casefold()


def test_table_option_drift_blocks_migration_preview():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    try:
        source.execute(
            "CREATE TABLE strict_probe (id INTEGER PRIMARY KEY, label TEXT) STRICT"
        )
        target.execute(
            "CREATE TABLE strict_probe (id INTEGER PRIMARY KEY, label TEXT)"
        )
        source.commit()
        target.commit()

        plan = build_data_migration_plan(source, target)

        assert plan["ready"] is False
        assert any("strict_probe" in item for item in plan["blockers"])
        assert target.execute("SELECT COUNT(*) FROM strict_probe").fetchone()[0] == 0
    finally:
        source.close()
        target.close()
