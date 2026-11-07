"""Integration test against Chappie's real schema initializers, isolated in tmp_path."""
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_real_chappie_schema_can_be_recreated_from_empty_target(tmp_path, monkeypatch):
    import server
    from storage.schema_migration import build_migration_plan, apply_migration_plan
    from storage.schema_audit import inspect_database, compare_database_inventories

    source_path = tmp_path / "chappie-source.sqlite3"
    monkeypatch.setattr(server, "DB_PATH", source_path)

    # Run the application's actual initialization path, including all cognitive
    # subsystem table initializers. This touches only a temporary local file.
    server.init_db()

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    target.row_factory = sqlite3.Row
    try:
        source_inventory = inspect_database(source)
        assert source_inventory["table_count"] >= 35

        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        assert plan["source_table_count"] == source_inventory["table_count"]
        assert plan["planned_statement_count"] > 0

        applied = apply_migration_plan(target, plan, apply=True)
        assert applied["applied"] is True
        assert applied["data_migration_included"] is False

        target_inventory = inspect_database(target)
        comparison = compare_database_inventories(source_inventory, target_inventory)
        assert comparison["compatible"] is True, comparison
        assert target_inventory["table_count"] == source_inventory["table_count"]

        # A second plan must be empty and idempotent.
        second_plan = build_migration_plan(source, target)
        assert second_plan["ready"] is True
        assert second_plan["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()
