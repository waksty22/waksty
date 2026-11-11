"""Compact, content-free safety summary for SQLite -> Turso migration previews."""
from __future__ import annotations

from collections import Counter
from typing import Any


def build_migration_safety_audit(plan: dict[str, Any]) -> dict[str, Any]:
    """Summarize schema and row-copy safeguards without exposing SQL or row data."""
    schema = plan.get("schema_plan") or {}
    statements = schema.get("statements") or []
    operation_counts = Counter(
        str(item.get("kind") or "unknown") for item in statements
    )
    tables = plan.get("tables") or []
    counts_available = bool(plan.get("ready")) and (
        bool(tables) or int(schema.get("source_table_count") or 0) == 0
    )
    source_rows = (
        sum(int(item.get("source_rows") or 0) for item in tables)
        if counts_available else None
    )
    target_rows = (
        sum(int(item.get("target_rows_before") or 0) for item in tables)
        if counts_available else None
    )
    diagnostics = plan.get("schema_diagnostics") or {}
    differences = diagnostics.get("differences") or []
    blockers = [str(item) for item in (plan.get("blockers") or [])]
    dependency_order = list(plan.get("table_order") or [])

    return {
        "read_only": True,
        "data_contents_exposed": False,
        "migration_executed": False,
        "data_copy_ready": bool(plan.get("ready")),
        "schema_plan": {
            "ready": bool(schema.get("ready")),
            "source_table_count": schema.get("source_table_count"),
            "target_table_count": schema.get("target_table_count"),
            "missing_tables": list(schema.get("missing_tables") or []),
            "missing_table_count": len(schema.get("missing_tables") or []),
            "planned_statement_count": schema.get("planned_statement_count", len(statements)),
            "operation_counts": dict(sorted(operation_counts.items())),
            "blocker_count": len(schema.get("blockers") or []),
        },
        "raw_schema_differences": {
            "count": len(differences),
            "distinct_from_plan_blockers": True,
        },
        "data_safety": {
            "row_counts_available": counts_available,
            "source_rows_total": source_rows,
            "target_rows_before_total": target_rows,
            "existing_target_rows_preserved": bool(
                plan.get("target_rows_are_preserved")
            ),
            "conflicts": plan.get("conflicting_rows", "not_assessed"),
            "target_only_rows_are_not_deleted": True,
            "source_rows_are_not_copied_during_audit": True,
        },
        "dependency_order": dependency_order,
        "dependency_table_count": len(dependency_order),
        "blockers": blockers[:20],
        "blockers_truncated": len(blockers) > 20,
        "notes": [
            "Les différences structurelles brutes ne sont pas nécessairement des bloqueurs du plan SQL.",
            "Les opérations de schéma planifiées et l'ordre des tables sont descriptifs ; aucune instruction n'est exécutée.",
            "Les lignes déjà présentes dans Turso doivent être conservées ; toute collision de clé doit interrompre et annuler le transfert.",
            "Un audit prêt ne constitue pas une autorisation de migration ni un basculement du backend.",
        ],
    }
