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
