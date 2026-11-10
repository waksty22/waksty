import json
import sqlite3

from storage.data_migration import (
    build_data_migration_plan,
    summarize_data_migration_plan,
)


def test_blocked_table_sql_report_keeps_actionable_read_only_diagnostics():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("""
        CREATE TABLE journal (
            id INTEGER PRIMARY KEY,
            entry TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE journal (
            id INTEGER PRIMARY KEY,
            entry TEXT NOT NULL /* legacy target annotation */
        )
    """)
    source.execute(
        "INSERT INTO journal(id, entry) VALUES (1, 'PRIVATE_SOURCE_CONTENT')"
    )
    target.execute(
        "INSERT INTO journal(id, entry) VALUES (2, 'PRIVATE_TARGET_CONTENT')"
    )

    try:
        plan = build_data_migration_plan(source, target)

        assert plan["ready"] is False
        assert plan["blockers"]
        assert plan["schema_diagnostics"]["read_only"] is True
        assert plan["schema_diagnostics"]["data_contents_exposed"] is False

        compact = summarize_data_migration_plan(plan)
        assert compact["version"] == "50.62"
        assert compact["ready"] is False
        assert compact["migration_executed"] is False
        assert compact["counts"]["blockers"] == 1
        assert compact["table_definition_differences"]
        difference = compact["table_definition_differences"][0]
        assert difference["table"] == "journal"
        assert len(difference["source_sha256"]) == 64
        assert len(difference["target_sha256"]) == 64
        assert difference["source_length"] > 0
        assert difference["target_length"] > 0
        assert difference["requires_manual_review"] is True
        assert "source_sql" not in difference
        assert "target_sql" not in difference
        assert "legacy target annotation" not in str(compact)

        serialized = json.dumps(compact)
        assert "PRIVATE_SOURCE_CONTENT" not in serialized
        assert "PRIVATE_TARGET_CONTENT" not in serialized
        assert compact["data_contents_exposed"] is False
    finally:
        source.close()
        target.close()
