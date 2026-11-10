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
            entry TEXT NOT NULL,
            mood TEXT NOT NULL DEFAULT 'PRIVATE_DEFAULT'
        )
    """)
    target.execute("""
        CREATE TABLE journal (
            id INTEGER PRIMARY KEY,
            entry TEXT NOT NULL /* legacy target annotation */
        )
    """)
    source.execute("CREATE INDEX idx_journal_mood ON journal(mood)")
    source.execute(
        "INSERT INTO journal(id, entry, mood) VALUES (1, 'PRIVATE_SOURCE_CONTENT', 'PRIVATE_MOOD')"
    )
    target.execute(
        "INSERT INTO journal(id, entry) VALUES (2, 'PRIVATE_TARGET_CONTENT')"
    )

    try:
        plan = build_data_migration_plan(source, target)
        assert plan["ready"] is False
        assert plan["schema_diagnostics"]["read_only"] is True
        assert plan["schema_diagnostics"]["data_contents_exposed"] is False

        compact = summarize_data_migration_plan(plan)
        assert compact["version"] == "50.63"
        assert compact["ready"] is False
        assert compact["migration_executed"] is False
        assert compact["table_definition_differences"]
        definition = compact["table_definition_differences"][0]
        assert definition["table"] == "journal"
        assert len(definition["source_sha256"]) == 64
        assert len(definition["target_sha256"]) == 64
        assert "source_sql" not in definition
        assert "target_sql" not in definition

        structural = compact["structural_differences"]
        assert any(
            item["category"] == "missing_column"
            and item["table"] == "journal"
            and item["item"] == "mood"
            for item in structural
        )
        assert any(
            item["category"] == "missing_index"
            and item["table"] == "journal"
            and item["item"] == "idx_journal_mood"
            for item in structural
        )
        serialized_structural = json.dumps(structural).lower()
        assert "create table" not in serialized_structural
        assert "private_default" not in serialized_structural
        assert "private_source_content" not in serialized_structural
        assert "private_target_content" not in serialized_structural
        assert "private_mood" not in serialized_structural
        assert all(
            not key.endswith("_sql")
            for item in structural
            for key in item
        )
        serialized = json.dumps(compact)
        for private_value in (
            "PRIVATE_SOURCE_CONTENT", "PRIVATE_TARGET_CONTENT",
            "PRIVATE_MOOD", "PRIVATE_DEFAULT", "legacy target annotation",
        ):
            assert private_value not in serialized
        assert compact["data_contents_exposed"] is False
        assert compact["read_only"] is True
        assert compact["migration_executed"] is False
    finally:
        source.close()
        target.close()
