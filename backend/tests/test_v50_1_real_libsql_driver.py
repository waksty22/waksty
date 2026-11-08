"""Exercise the actual libsql driver locally, without contacting Turso."""
import sqlite3

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from storage.schema_migration import build_migration_plan, apply_migration_plan
from storage.logical_backup import export_logical_backup, verify_logical_backup


def test_schema_migration_runs_through_real_libsql_driver_in_memory(tmp_path):
    source = sqlite3.connect(":memory:")
    native = libsql.connect(":memory:")
    target = adapt_libsql_connection(native)
    try:
        source.executescript("""
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY,
                skill_name TEXT NOT NULL,
                xp REAL NOT NULL DEFAULT 0.0
            );
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY,
                entry TEXT NOT NULL
            );
            CREATE INDEX idx_journal_id ON journal(id);
        """)
        target.execute("""
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY,
                skill_name TEXT NOT NULL
            )
        """)
        target.execute("INSERT INTO skills(skill_name) VALUES (?)", ("keep-me",))
        target.commit()

        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        result = apply_migration_plan(target, plan, apply=True)
        assert result["applied"]
        assert target.execute("SELECT skill_name, xp FROM skills").fetchone()["skill_name"] == "keep-me"
        assert target.execute("SELECT xp FROM skills").fetchone()["xp"] == 0.0
        assert target.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 0
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_journal_id'"
        ).fetchone()[0] == 1

        # Exercise the same consistent-snapshot exporter against the actual
        # local libSQL driver, without opening a remote Turso connection.
        target.execute("INSERT INTO journal(entry) VALUES (?)", ("local libSQL test row",))
        target.commit()
        backup_path = tmp_path / "libsql-logical-backup.json"
        backup = export_logical_backup(target, backup_path)
        assert backup["verified"] is True
        assert verify_logical_backup(backup_path)["valid"] is True
        assert backup["total_rows"] == 2

        second = build_migration_plan(source, target)
        assert second["ready"]
        assert second["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()
