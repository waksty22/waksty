"""Read-only SQLite/libSQL schema inspection and comparison helpers."""
from __future__ import annotations

import re
from typing import Any


def _value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_sql(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip().rstrip(";").casefold()


def inspect_schema(connection: Any) -> dict[str, Any]:
    """Return tables, columns and SQL-backed objects without changing the DB."""
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY type, name
        """
    ).fetchall()

    objects: dict[str, dict[str, Any]] = {}
    tables: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        kind = str(_value(row, "type", 0))
        name = str(_value(row, "name", 1))
        table_name = str(_value(row, "tbl_name", 2))
        sql = _value(row, "sql", 3)
        objects[f"{kind}:{name}"] = {
            "type": kind,
            "name": name,
            "table": table_name,
            "sql": _normalize_sql(sql),
        }
        if kind == "table":
            column_rows = connection.execute(
                f"PRAGMA table_info({_quote_identifier(name)})"
            ).fetchall()
            tables[name] = [
                {
                    "name": str(_value(column, "name", 1)),
                    "type": str(_value(column, "type", 2) or "").upper(),
                    "notnull": int(_value(column, "notnull", 3)),
                    "default": _value(column, "dflt_value", 4),
                    "primary_key_position": int(_value(column, "pk", 5)),
                }
                for column in column_rows
            ]

    return {"objects": objects, "tables": tables}


def compare_schemas(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare inspected schemas and return a deterministic difference report."""
    left_objects = left.get("objects", {})
    right_objects = right.get("objects", {})
    left_tables = left.get("tables", {})
    right_tables = right.get("tables", {})

    missing_right = sorted(set(left_objects) - set(right_objects))
    missing_left = sorted(set(right_objects) - set(left_objects))
    changed_objects = sorted(
        key for key in set(left_objects) & set(right_objects)
        if left_objects[key] != right_objects[key]
    )
    changed_columns = sorted(
        name for name in set(left_tables) & set(right_tables)
        if left_tables[name] != right_tables[name]
    )

    return {
        "compatible": not (
            missing_right or missing_left or changed_objects or changed_columns
        ),
        "missing_from_right": missing_right,
        "missing_from_left": missing_left,
        "changed_objects": changed_objects,
        "changed_columns": changed_columns,
        "left_table_count": len(left_tables),
        "right_table_count": len(right_tables),
        "left_object_count": len(left_objects),
        "right_object_count": len(right_objects),
    }



def inspect_database(connection: Any) -> dict[str, Any]:
    """Read-only inventory of schema, row counts, indexes and FK health.

    No user row contents are returned. Only aggregate counts and structural
    metadata are exposed, suitable for an authenticated diagnostic endpoint.
    """
    schema = inspect_schema(connection)
    table_details: dict[str, dict[str, Any]] = {}
    total_rows = 0

    for table_name, columns in schema["tables"].items():
        quoted = _quote_identifier(table_name)
        row_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        )
        total_rows += row_count

        foreign_keys = connection.execute(
            f"PRAGMA foreign_key_list({quoted})"
        ).fetchall()
        indexes = connection.execute(
            f"PRAGMA index_list({quoted})"
        ).fetchall()

        table_details[table_name] = {
            "row_count": row_count,
            "columns": columns,
            "foreign_keys": [
                {
                    "id": int(_value(row, "id", 0)),
                    "sequence": int(_value(row, "seq", 1)),
                    "referenced_table": str(_value(row, "table", 2)),
                    "from_column": str(_value(row, "from", 3)),
                    "to_column": str(_value(row, "to", 4)),
                    "on_update": str(_value(row, "on_update", 5)),
                    "on_delete": str(_value(row, "on_delete", 6)),
                }
                for row in foreign_keys
            ],
            "indexes": [
                {
                    "name": str(_value(row, "name", 1)),
                    "unique": bool(_value(row, "unique", 2)),
                    "origin": str(_value(row, "origin", 3)),
                }
                for row in indexes
            ],
        }

    try:
        fk_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        fk_check_supported = True
    except Exception:
        fk_violations = None
        fk_check_supported = False

    return {
        "schema": schema,
        "tables": table_details,
        "table_count": len(table_details),
        "object_count": len(schema["objects"]),
        "total_rows": total_rows,
        "foreign_key_violations": fk_violations,
        "foreign_key_check_supported": fk_check_supported,
    }


def compare_database_inventories(
    local: dict[str, Any], remote: dict[str, Any]
) -> dict[str, Any]:
    """Compare two structural inventories without reading user row contents."""
    schema_comparison = compare_schemas(local["schema"], remote["schema"])
    local_tables = local["tables"]
    remote_tables = remote["tables"]
    all_names = sorted(set(local_tables) | set(remote_tables))
    row_differences = {
        name: {
            "local": local_tables.get(name, {}).get("row_count"),
            "remote": remote_tables.get(name, {}).get("row_count"),
        }
        for name in all_names
        if local_tables.get(name, {}).get("row_count")
        != remote_tables.get(name, {}).get("row_count")
    }
    return {
        "schema": schema_comparison,
        "row_count_differences": row_differences,
        "local_total_rows": local["total_rows"],
        "remote_total_rows": remote["total_rows"],
        "local_foreign_key_violations": local["foreign_key_violations"],
        "remote_foreign_key_violations": remote["foreign_key_violations"],
        "compatible": schema_comparison["compatible"] and not row_differences,
    }
