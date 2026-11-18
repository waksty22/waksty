"""Read-only global SQLite/Turso persistence inventory.

Reports schema metadata and aggregate row counts only; never returns business
row contents, SQL definitions, credentials, or database paths.
"""
from __future__ import annotations

from typing import Any

from storage.schema_audit import _quote_identifier, compare_schemas, inspect_schema


def _inventory(connection: Any, user_id: str) -> dict[str, Any]:
    schema = inspect_schema(connection)
    tables: dict[str, dict[str, Any]] = {}
    for name, columns in sorted(schema["tables"].items()):
        quoted = _quote_identifier(name)
        total_rows = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        )
        has_user_scope = any(column["name"] == "user_id" for column in columns)
        user_rows = None
        if has_user_scope:
            user_rows = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {quoted} WHERE user_id=?",
                    (user_id,),
                ).fetchone()[0]
            )
        foreign_keys = connection.execute(
            f"PRAGMA foreign_key_list({quoted})"
        ).fetchall()
        indexes = connection.execute(
            f"PRAGMA index_list({quoted})"
        ).fetchall()
        tables[name] = {
            "rows_total": total_rows,
            "rows_for_authenticated_user": user_rows,
            "has_user_scope": has_user_scope,
            "column_count": len(columns),
            "foreign_key_count": len(foreign_keys),
            "index_count": len(indexes),
        }

    object_types: dict[str, int] = {}
    for item in schema["objects"].values():
        kind = str(item["type"])
        object_types[kind] = object_types.get(kind, 0) + 1

    try:
        fk_violations = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        fk_check_supported = True
    except Exception:
        fk_violations = None
        fk_check_supported = False

    return {
        "table_count": len(tables),
        "object_count": len(schema["objects"]),
        "total_rows": sum(item["rows_total"] for item in tables.values()),
        "object_types": object_types,
        "tables": tables,
        "foreign_key_violations": fk_violations,
        "foreign_key_check_supported": fk_check_supported,
        "table_xinfo_supported": schema["capabilities"]["table_xinfo_supported"],
        "_schema": schema,
    }


def inspect_global_persistence(
    sqlite_connection: Any,
    turso_connection: Any | None,
    active_backend: str,
    user_id: str,
    turso_status: str = "connected",
) -> dict[str, Any]:
    """Compare both stores using read-only schema metadata and aggregate counts."""
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("user_id est obligatoire.")

    sqlite = _inventory(sqlite_connection, user_id)
    turso = _inventory(turso_connection, user_id) if turso_connection is not None else None
    comparison: dict[str, Any]
    if turso is None:
        comparison = {
            "available": False,
            "status": turso_status,
            "missing_tables_in_turso": None,
            "extra_tables_in_turso": None,
            "schema_compatible": None,
            "different_schema_objects": None,
        }
    else:
        schema_comparison = compare_schemas(sqlite["_schema"], turso["_schema"])
        sqlite_tables = set(sqlite["tables"])
        turso_tables = set(turso["tables"])
        comparison = {
            "available": True,
            "status": "compared",
            "missing_tables_in_turso": sorted(sqlite_tables - turso_tables),
            "extra_tables_in_turso": sorted(turso_tables - sqlite_tables),
            "schema_compatible": schema_comparison["compatible"],
            "different_schema_objects": (
                len(schema_comparison["missing_from_right"])
                + len(schema_comparison["missing_from_left"])
                + len(schema_comparison["changed_objects"])
                + len(schema_comparison["changed_columns"])
            ),
        }

    sqlite.pop("_schema", None)
    if turso is not None:
        turso.pop("_schema", None)
    return {
        "read_only": True,
        "active_backend": str(active_backend),
        "user_scope": "authenticated_user",
        "sqlite": sqlite,
        "turso": turso,
        "comparison": comparison,
        "note": (
            "Inventaire structurel et compteurs agrégés uniquement. "
            "Il ne vérifie ni l'égalité du contenu des lignes ni la survie "
            "des données après redémarrage."
        ),
    }
