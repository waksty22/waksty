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


def _table_columns(connection: Any, table_name: str) -> dict[str, tuple[Any, ...]]:
    rows = connection.execute(
        f"PRAGMA table_info({_quote_identifier(table_name)})"
    ).fetchall()
    return {
        str(_row_value(row, "name", 1)): (
            str(_row_value(row, "type", 2) or "").upper(),
            int(_row_value(row, "notnull", 3)),
            str(_row_value(row, "dflt_value", 4)),
            int(_row_value(row, "pk", 5)),
        )
        for row in rows
    }


def _foreign_key_signature(connection: Any, table_name: str) -> list[tuple[Any, ...]]:
    rows = connection.execute(
        f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
    ).fetchall()
    return sorted(
        (
            str(_row_value(row, "table", 2)),
            str(_row_value(row, "from", 3)),
            str(_row_value(row, "to", 4)),
            str(_row_value(row, "on_update", 5)),
            str(_row_value(row, "on_delete", 6)),
        )
        for row in rows
    )


def _normalized_sql(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


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
    # SQLite object names share one namespace. Never overwrite an object of
    # another kind merely because its name matches a source object.
    target_by_name = {item["name"]: item for item in target_objects.values()}
    for item in source_objects.values():
        conflict = target_by_name.get(item["name"])
        if conflict and conflict["type"] != item["type"]:
            blockers.append(
                f"Conflit de type pour {item['name']} : "
                f"{conflict['type']} côté cible, {item['type']} côté source."
            )
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
        for column_name in sorted(set(source_columns) & set(target_columns)):
            if source_columns[column_name] != target_columns[column_name]:
                blockers.append(
                    f"{table_name}.{column_name}: définition différente entre source et cible."
                )
        if _foreign_key_signature(source, table_name) != _foreign_key_signature(target, table_name):
            blockers.append(f"{table_name}: contraintes de clés étrangères différentes.")
        missing_columns = sorted(set(source_columns) - set(target_columns))
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
            existing = target_objects[key]
            if item["type"] in {"index", "view", "trigger"}:
                if _normalized_sql(item["sql"]) != _normalized_sql(existing["sql"]):
                    blockers.append(
                        f"{item['type']} {item['name']}: définition différente entre source et cible."
                    )
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
    commit = getattr(target, "commit", None)
    rollback = getattr(target, "rollback", None)
    if not callable(commit) or not callable(rollback):
        raise TypeError("La connexion cible doit prendre en charge commit() et rollback().")

    executed: list[str] = []
    try:
        target.execute("BEGIN")
        for statement in plan.get("statements", []):
            target.execute(statement["sql"])
            executed.append(statement["object"])
        commit()
    except Exception:
        rollback()
        raise
    return {
        "applied": True,
        "executed_count": len(executed),
        "executed_objects": executed,
        "data_migration_included": False,
        "existing_rows_modified": False,
    }
