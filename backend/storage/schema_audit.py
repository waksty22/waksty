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
    table_xinfo_supported = True
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
            # table_xinfo also includes generated and hidden columns. Some
            # libSQL builds may not expose it; retain a visible fallback while
            # reporting that the extended inventory is incomplete.
            try:
                column_rows = connection.execute(
                    f"PRAGMA table_xinfo({_quote_identifier(name)})"
                ).fetchall()
                table_xinfo_supported = bool(column_rows) or table_xinfo_supported
                extended_columns = bool(column_rows)
            except Exception:
                column_rows = []
                extended_columns = False
            if not column_rows:
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
                    "hidden": int(_value(column, "hidden", 6)) if extended_columns else 0,
                    "generated_or_hidden": bool(
                        int(_value(column, "hidden", 6)) if extended_columns else 0
                    ),
                    "metadata_complete": extended_columns,
                }
                for column in column_rows
            ]

    return {
        "objects": objects,
        "tables": tables,
        "capabilities": {
            "table_xinfo_supported": table_xinfo_supported,
        },
    }


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

        index_details = []
        for index_row in indexes:
            index_name = str(_value(index_row, "name", 1))
            index_quoted = _quote_identifier(index_name)
            index_xinfo_supported = True
            try:
                index_columns = connection.execute(
                    f"PRAGMA index_xinfo({index_quoted})"
                ).fetchall()
                extended_index_columns = bool(index_columns)
            except Exception:
                index_columns = []
                extended_index_columns = False
            if not index_columns:
                try:
                    index_columns = connection.execute(
                        f"PRAGMA index_info({index_quoted})"
                    ).fetchall()
                except Exception:
                    index_columns = []
                index_xinfo_supported = False
            index_details.append({
                "name": index_name,
                "unique": bool(_value(index_row, "unique", 2)),
                "origin": str(_value(index_row, "origin", 3)),
                "partial": bool(_value(index_row, "partial", 4)),
                "columns": [
                    {
                        "sequence": int(_value(column, "seqno", 0)),
                        "name": _value(column, "name", 2),
                        "descending": bool(_value(column, "desc", 3)) if extended_index_columns else None,
                        "collation": _value(column, "coll", 4) if extended_index_columns else None,
                        "key_column": bool(_value(column, "key", 5)) if extended_index_columns else None,
                    }
                    for column in index_columns
                ],
                "metadata_complete": extended_index_columns,
                "sql": schema["objects"].get(
                    f"index:{index_name}", {}
                ).get("sql"),
            })

        table_details[table_name] = {
            "row_count": row_count,
            "index_xinfo_supported": all(
                item.get("metadata_complete", False) for item in index_details
            ),
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
                    "match": str(_value(row, "match", 7)),
                }
                for row in foreign_keys
            ],
            "indexes": index_details,
            "create_sql": schema["objects"].get(
                f"table:{table_name}", {}
            ).get("sql"),
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
        "metadata_capabilities": {
            "table_xinfo_supported": schema.get("capabilities", {}).get("table_xinfo_supported", False),
            "index_xinfo_supported": all(
                detail.get("index_xinfo_supported", True)
                for detail in table_details.values()
            ),
        },
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
    details: list[dict[str, Any]] = []

    def add_difference(
        category: str,
        severity: str,
        table: str | None,
        item: str,
        local_value: Any = None,
        remote_value: Any = None,
        explanation: str = "",
    ) -> None:
        details.append({
            "category": category,
            "severity": severity,
            "table": table,
            "item": item,
            "local": local_value,
            "remote": remote_value,
            "explanation": explanation,
        })

    for table_name in sorted(set(local_tables) - set(remote_tables)):
        add_difference(
            "missing_table", "blocking", table_name, table_name,
            local_tables[table_name], None,
            "Table source absente de Turso.",
        )
    for table_name in sorted(set(remote_tables) - set(local_tables)):
        add_difference(
            "extra_table", "blocking", table_name, table_name,
            None, remote_tables[table_name],
            "Table présente uniquement dans Turso ; préserver ses données.",
        )

    column_fields = ("type", "notnull", "default", "primary_key_position")
    for table_name in sorted(set(local_tables) & set(remote_tables)):
        local_detail = local_tables[table_name]
        remote_detail = remote_tables[table_name]
        local_columns = {
            column["name"]: column for column in local_detail.get("columns", [])
        }
        remote_columns = {
            column["name"]: column for column in remote_detail.get("columns", [])
        }
        for column_name in sorted(set(local_columns) - set(remote_columns)):
            add_difference(
                "missing_column", "blocking", table_name, column_name,
                local_columns[column_name], None,
                "Colonne source absente de Turso.",
            )
        for column_name in sorted(set(remote_columns) - set(local_columns)):
            add_difference(
                "extra_column", "blocking", table_name, column_name,
                None, remote_columns[column_name],
                "Colonne présente uniquement dans Turso.",
            )
        for column_name in sorted(set(local_columns) & set(remote_columns)):
            left_column = local_columns[column_name]
            right_column = remote_columns[column_name]
            changed = {
                field: {"local": left_column.get(field), "remote": right_column.get(field)}
                for field in column_fields
                if left_column.get(field) != right_column.get(field)
            }
            if changed:
                add_difference(
                    "column_definition", "blocking", table_name, column_name,
                    left_column, right_column,
                    "Différence de type, nullabilité, valeur par défaut ou clé primaire.",
                )

        local_fks = sorted(
            local_detail.get("foreign_keys", []),
            key=lambda item: (
                item.get("id"), item.get("sequence"), item.get("referenced_table", ""),
                item.get("from_column", ""), item.get("to_column", ""),
            ),
        )
        remote_fks = sorted(
            remote_detail.get("foreign_keys", []),
            key=lambda item: (
                item.get("id"), item.get("sequence"), item.get("referenced_table", ""),
                item.get("from_column", ""), item.get("to_column", ""),
            ),
        )
        if local_fks != remote_fks:
            add_difference(
                "foreign_keys", "blocking", table_name, "foreign_key_list",
                local_fks, remote_fks,
                "Différence de relations ou d'actions ON UPDATE / ON DELETE.",
            )

        local_indexes = {
            item["name"]: item for item in local_detail.get("indexes", [])
        }
        remote_indexes = {
            item["name"]: item for item in remote_detail.get("indexes", [])
        }
        for index_name in sorted(set(local_indexes) - set(remote_indexes)):
            index = local_indexes[index_name]
            is_constraint = bool(index.get("unique")) or index.get("origin") in ("u", "pk")
            add_difference(
                "missing_unique_constraint" if is_constraint else "missing_index",
                "blocking" if is_constraint else "important",
                table_name, index_name, index, None,
                "Contrainte UNIQUE / clé primaire absente de Turso." if is_constraint
                else "Index absent de Turso.",
            )
        for index_name in sorted(set(remote_indexes) - set(local_indexes)):
            index = remote_indexes[index_name]
            is_constraint = bool(index.get("unique")) or index.get("origin") in ("u", "pk")
            add_difference(
                "extra_unique_constraint" if is_constraint else "extra_index",
                "blocking" if is_constraint else "important",
                table_name, index_name, None, index,
                "Contrainte UNIQUE / clé primaire présente uniquement dans Turso." if is_constraint
                else "Index présent uniquement dans Turso.",
            )
        for index_name in sorted(set(local_indexes) & set(remote_indexes)):
            if local_indexes[index_name] != remote_indexes[index_name]:
                left_index = local_indexes[index_name]
                right_index = remote_indexes[index_name]
                is_constraint = any(
                    bool(index.get("unique")) or index.get("origin") in ("u", "pk")
                    for index in (left_index, right_index)
                )
                add_difference(
                    "unique_constraint_definition" if is_constraint else "index_definition",
                    "blocking" if is_constraint else "important",
                    table_name, index_name, left_index, right_index,
                    "Définition de contrainte UNIQUE / clé primaire différente." if is_constraint
                    else "Différence de colonnes, ordre, unicité ou définition SQL de l'index.",
                )

        if local_detail.get("create_sql") != remote_detail.get("create_sql"):
            add_difference(
                "table_constraints_or_options", "blocking", table_name,
                "CREATE TABLE",
                local_detail.get("create_sql"), remote_detail.get("create_sql"),
                "Définition SQL différente : examiner CHECK, UNIQUE et options de table.",
            )

    local_objects = local.get("schema", {}).get("objects", {})
    remote_objects = remote.get("schema", {}).get("objects", {})
    for object_name in sorted(set(local_objects) | set(remote_objects)):
        left_object = local_objects.get(object_name)
        right_object = remote_objects.get(object_name)
        if left_object == right_object:
            continue
        object_type = object_name.split(":", 1)[0]
        if object_type == "table":
            continue  # Already classified with table-level and column details.
        severity = "important" if object_type in ("index", "view", "trigger") else "blocking"
        add_difference(
            object_type + "_definition", severity, None, object_name,
            left_object, right_object,
            "Objet SQL absent ou défini différemment.",
        )

    for table_name, counts in row_differences.items():
        add_difference(
            "row_count", "informational", table_name, table_name,
            counts["local"], counts["remote"],
            "Les volumes diffèrent ; cela ne compare pas le contenu des lignes.",
        )

    severity_order = {"blocking": 0, "important": 1, "informational": 2}
    details.sort(
        key=lambda item: (
            severity_order.get(item["severity"], 3),
            item.get("table") or "",
            item.get("category") or "",
            item.get("item") or "",
        )
    )
    severity_counts = {
        severity: sum(1 for item in details if item["severity"] == severity)
        for severity in ("blocking", "important", "informational")
    }
    blocking = severity_counts["blocking"] > 0
    important = severity_counts["important"] > 0
    schema_ready = not blocking and not important

    return {
        "schema": schema_comparison,
        "row_count_differences": row_differences,
        "local_total_rows": local["total_rows"],
        "remote_total_rows": remote["total_rows"],
        "local_foreign_key_violations": local["foreign_key_violations"],
        "remote_foreign_key_violations": remote["foreign_key_violations"],
        "compatible": schema_comparison["compatible"] and not row_differences,
        "detailed_audit": {
            "version": "50.54",
            "read_only": True,
            "data_contents_exposed": False,
            "schema_readiness": "ready" if schema_ready else "blocked",
            "migration_readiness": "not_assessed",
            "migration_blocked_by_schema": not schema_ready,
            "severity_counts": severity_counts,
            "differences": details,
            "notes": [
                "Les définitions SQL de tables sont comparées pour détecter notamment CHECK, UNIQUE et options de table.",
                "Les différences de volumes sont informatives et ne prouvent pas l'égalité ou l'inégalité du contenu.",
                "Aucune donnée métier n'est lue ou exposée.",
            ],
        },
    }
