from storage.migration_audit import build_migration_safety_audit


def test_migration_safety_audit_is_content_free_and_reports_preservation():
    plan = {
        "ready": True,
        "schema_plan": {
            "ready": True,
            "source_table_count": 2,
            "target_table_count": 1,
            "missing_tables": ["child"],
            "planned_statement_count": 2,
            "statements": [
                {"kind": "create_table", "object": "child", "sql": "CREATE TABLE child (secret TEXT)"},
                {"kind": "create_index", "object": "idx_child", "sql": "CREATE INDEX idx_child ON child(id)"},
            ],
            "blockers": [],
        },
        "schema_diagnostics": {
            "differences": [{"category": "missing_table", "local": "private schema detail"}],
        },
        "tables": [
            {"table": "parent", "source_rows": 0, "target_rows_before": 5},
            {"table": "child", "source_rows": 0, "target_rows_before": 0},
        ],
        "table_order": ["parent", "child"],
        "target_rows_are_preserved": True,
        "conflicting_rows": "abort_and_rollback",
        "blockers": [],
    }

    audit = build_migration_safety_audit(plan)

    assert audit["read_only"] is True
    assert audit["migration_executed"] is False
    assert audit["data_safety"]["source_rows_total"] == 0
    assert audit["data_safety"]["target_rows_before_total"] == 5
    assert audit["data_safety"]["existing_target_rows_preserved"] is True
    assert audit["data_safety"]["conflicts"] == "abort_and_rollback"
    assert audit["schema_plan"]["operation_counts"] == {
        "create_index": 1,
        "create_table": 1,
    }
    assert audit["dependency_order"] == ["parent", "child"]
    assert "secret" not in str(audit)
    assert "private schema detail" not in str(audit)


def test_migration_safety_audit_does_not_claim_row_counts_when_plan_blocked():
    audit = build_migration_safety_audit({
        "ready": False,
        "schema_plan": {
            "ready": False,
            "source_table_count": 2,
            "target_table_count": 1,
            "missing_tables": ["child"],
            "statements": [],
            "blockers": ["manual review"],
        },
        "blockers": ["manual review"],
    })

    assert audit["data_copy_ready"] is False
    assert audit["data_safety"]["row_counts_available"] is False
    assert audit["data_safety"]["source_rows_total"] is None
    assert audit["data_safety"]["target_rows_before_total"] is None
    assert audit["data_safety"]["existing_target_rows_preserved"] is False
