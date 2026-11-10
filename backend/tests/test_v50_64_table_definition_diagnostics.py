import json
import sqlite3

from storage.data_migration import (
    build_data_migration_plan,
    summarize_data_migration_plan,
)


def test_table_definition_diagnostics_compare_semantic_components_without_leaking_values():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE autobiographical_events (
            id INTEGER PRIMARY KEY,
            source_conversation_id INTEGER REFERENCES conversations(id)
        )
    """)
    source.execute("INSERT INTO conversations VALUES (1, 'u', 'user', 'PRIVATE_SOURCE', 'now')")
    target.execute("INSERT INTO conversations VALUES (2, 'u', 'system', 'PRIVATE_TARGET', 'now')")
    target.execute("INSERT INTO autobiographical_events VALUES (1, 2)")
    try:
        plan = build_data_migration_plan(source, target)
        compact = summarize_data_migration_plan(plan)
        assert compact["version"] == "50.64"
        assert compact["ready"] is False
        definition = next(
            item for item in compact["table_definition_differences"]
            if item["table"] == "conversations"
        )
        components = definition["semantic_components"]
        assert components["source"]["columns_sha256"] == components["target"]["columns_sha256"]
        assert components["source"]["foreign_keys_sha256"] == components["target"]["foreign_keys_sha256"]
        assert components["source"]["unique_constraints_sha256"] == components["target"]["unique_constraints_sha256"]
        assert components["source"]["check_constraints_sha256"] != components["target"]["check_constraints_sha256"]
        serialized = json.dumps(compact).lower()
        assert "private_source" not in serialized
        assert "private_target" not in serialized
        assert "create table" not in serialized
        assert compact["read_only"] is True
        assert compact["data_contents_exposed"] is False
        assert compact["migration_executed"] is False
    finally:
        source.close()
        target.close()
