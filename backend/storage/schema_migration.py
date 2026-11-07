"""Plan and apply additive SQLite -> libSQL schema migrations safely.

The default operation is planning only. Applying changes requires an explicit
apply=True argument from a deliberate caller. Existing rows are never copied,
updated, or deleted by this module.
"""
from __future__ import annotations

from typing import Any

from storage.schema_audit import _quote_identifier

# Only explicitly reviewed additive column changes may be applied to an
# existing table. Unknown column drift is a blocker, never guessed.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "skills": {"xp": "REAL NOT NULL DEFAULT 0.0"},
}


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _schema_objects(connection: Any) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY type, name
        """
    ).fetchall()
    return {
        f"{_row_value(row, 'type', 0)}:{_row_value(row, 'name', 1)}": {
            "type": str(_row_value(row, "type", 0)),
            "name": str(_row_value(row, "name", 1)),
            "table": str(_row_value(row, "tbl_name", 2)),
            "sql": _row_value(row, "sql", 3),
        }
        for row in rows
    }


def _table_columns(connection: Any, table_name: str) -> set[str]:
    rows = connection.execute(
        f"PRAGMA table_info({_quote_identifier(table_name)})"
    ).fetchall()
    return {str(_row_value(row, "name", 1)) for row in rows}


def build_migration_plan(
    source: Any,
    target: Any,
    additive_columns: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-mutating plan from source schema to target."""
    allowed = ADDITIVE_COLUMNS if additive_columns is None else additive_columns
    source_objects = _schema_objects(source)
    target_objects = _schema_objects(target)
    source_tables = {
        item["name"]: item for item in source_objects.values()
        if item["type"] == "table"
    }
    target_tables = {
        item["name"]: item for item in target_objects.values()
        if item["type"] == "table"
    }

    statements: list[dict[str, str]] = []
    blockers: list[str] = []
    missing_tables = sorted(set(source_tables) - set(target_tables))

    for table_name in missing_tables:
        create_sql = source_tables[table_name]["sql"]
        if not create_sql or not str(create_sql).lstrip().upper().startswith("CREATE TABLE"):
            blockers.append(f"Définition absente ou non prise en charge pour la table {table_name}.")
            continue
        statements.append({
            "kind": "create_table",
            "object": table_name,
            "sql": str(create_sql),
        })

    for table_name in sorted(set(source_tables) & set(target_tables)):
        source_columns = _table_columns(source, table_name)
        target_columns = _table_columns(target, table_name)
        missing_columns = sorted(source_columns - target_columns)
        unexpected = [
            column for column in missing_columns
            if column not in allowed.get(table_name, {})
        ]
        if unexpected:
            blockers.append(
                f"{table_name}: colonnes manquantes non autorisées : {', '.join(unexpected)}."
            )
            continue
        for column_name in missing_columns:
            declaration = allowed[table_name][column_name]
            statements.append({
                "kind": "add_column",
                "object": f"{table_name}.{column_name}",
                "sql": (
                    f"ALTER TABLE {_quote_identifier(table_name)} "
                    f"ADD COLUMN {_quote_identifier(column_name)} {declaration}"
                ),
            })

    for key, item in sorted(source_objects.items()):
        if key in target_objects:
            continue
        if item["type"] == "table":
            continue
        if item["type"] == "index":
            if not item["sql"]:
                # SQLite autoindexes have no SQL and are created with their table.
                continue
            statements.append({
                "kind": "create_index",
                "object": item["name"],
                "sql": str(item["sql"]),
            })
        else:
            blockers.append(
                f"Objet {item['type']} non pris en charge automatiquement : {item['name']}."
            )

    # Tables first, additive columns second, indexes last.
    order = {"create_table": 0, "add_column": 1, "create_index": 2}
    statements.sort(key=lambda item: (order[item["kind"]], item["object"]))

    return {
        "read_only": True,
        "source_table_count": len(source_tables),
        "target_table_count": len(target_tables),
        "missing_tables": missing_tables,
        "planned_statement_count": len(statements),
        "statements": statements,
        "blockers": blockers,
        "ready": not blockers,
        "data_migration_included": False,
        "existing_rows_modified": False,
    }


def apply_migration_plan(
    target: Any,
    plan: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Apply a reviewed plan only when apply=True; never migrates table rows."""
    if not apply:
        return {
            "applied": False,
            "reason": "dry_run",
            "executed_count": 0,
            "remaining_count": plan.get("planned_statement_count", 0),
        }
    if not plan.get("ready"):
        raise ValueError("Migration bloquée : le plan contient des incompatibilités.")
    executed: list[str] = []
    for statement in plan.get("statements", []):
        target.execute(statement["sql"])
        executed.append(statement["object"])
    commit = getattr(target, "commit", None)
    if callable(commit):
        commit()
    return {
        "applied": True,
        "executed_count": len(executed),
        "executed_objects": executed,
        "data_migration_included": False,
        "existing_rows_modified": False,
    }
