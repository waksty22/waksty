"""Guarded, idempotent SQLite -> libSQL row migration.

The default path is a read-only preview. Applying requires apply=True and
runs schema changes plus row copies in one target transaction. Existing target
rows are preserved; conflicting primary/unique keys abort and roll back.
No row contents are returned in reports.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from storage.schema_audit import (
    _quote_identifier,
    compare_database_inventories,
    inspect_database,
)
from storage.schema_migration import (
    apply_schema_statement,
    build_migration_plan,
    _row_value,
    _check_constraint_signature,
    _foreign_key_signature,
    _unique_index_signature,
)


def _columns(connection: Any, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"PRAGMA table_xinfo({_quote_identifier(table)})"
    ).fetchall()
    if not rows:
        # A table with no columns is not a valid migration source.
        raise ValueError(f"Métadonnées de colonnes indisponibles pour {table}.")
    result = []
    for row in rows:
        result.append({
            "cid": int(_row_value(row, "cid", 0)),
            "name": str(_row_value(row, "name", 1)),
            "type": str(_row_value(row, "type", 2) or ""),
            "notnull": int(_row_value(row, "notnull", 3)),
            "default": _row_value(row, "dflt_value", 4),
            "pk": int(_row_value(row, "pk", 5)),
            "hidden": int(_row_value(row, "hidden", 6)),
        })
    return result


def _objects(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'chappie_storage_migration_state'
        ORDER BY name
        """
    ).fetchall()
    return [
        {
            "name": str(_row_value(row, "name", 1)),
            "sql": _row_value(row, "sql", 2),
        }
        for row in rows
    ]


def _foreign_key_dependencies(connection: Any, table: str) -> set[str]:
    rows = connection.execute(
        f"PRAGMA foreign_key_list({_quote_identifier(table)})"
    ).fetchall()
    return {
        str(_row_value(row, "table", 2))
        for row in rows
    }


def _table_order(connection: Any, table_names: list[str]) -> list[str]:
    known = set(table_names)
    dependencies = {
        name: _foreign_key_dependencies(connection, name) & known
        for name in table_names
    }
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(
                f"Dépendance circulaire entre tables : {name}. "
                "Migration bloquée plutôt que désactiver les clés étrangères."
            )
        visiting.add(name)
        for dependency in sorted(dependencies[name]):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(table_names):
        visit(name)
    return ordered


def _normalize(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"blob_hex": bytes(value).hex()}
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"float": repr(value)}
        return {"float": value.hex()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return {"type": type(value).__name__, "value": str(value)}


def _row_digest_update(digest: Any, table: str, columns: list[str], values: tuple[Any, ...]) -> None:
    payload = {
        "table": table,
        "columns": columns,
        "values": [_normalize(value) for value in values],
    }
    digest.update(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(b"\n")


def _row_exists(
    target: Any,
    table: str,
    columns: list[str],
    values: tuple[Any, ...],
    primary_keys: list[str],
) -> tuple[bool, tuple[Any, ...] | None]:
    lookup_columns = primary_keys or columns
    predicates = " AND ".join(
        f"{_quote_identifier(name)} IS ?" for name in lookup_columns
    )
    lookup_values = tuple(values[columns.index(name)] for name in lookup_columns)
    selected = ", ".join(_quote_identifier(name) for name in columns)
    cursor = target.execute(
        f"SELECT {selected} FROM {_quote_identifier(table)} "
        f"WHERE {predicates} LIMIT 1",
        lookup_values,
    )
    row = cursor.fetchone()
    return row is not None, tuple(row) if row is not None else None


def _row_match_count(
    target: Any,
    table: str,
    columns: list[str],
    values: tuple[Any, ...],
) -> int:
    """Count identical rows for tables without a primary key, preserving duplicates."""
    predicates = " AND ".join(
        f"{_quote_identifier(name)} IS ?" for name in columns
    )
    return int(target.execute(
        f"SELECT COUNT(*) FROM {_quote_identifier(table)} WHERE {predicates}",
        values,
    ).fetchone()[0])


def _preflight_extra_columns(
    source_columns: list[dict[str, Any]],
    target_columns: list[dict[str, Any]],
    table: str,
) -> list[str]:
    source_names = {column["name"] for column in source_columns}
    blockers = []
    for column in target_columns:
        if column["name"] in source_names or column["hidden"] in (2, 3):
            continue
        if column["hidden"] == 1:
            blockers.append(f"{table}.{column['name']}: colonne cachée cible non prise en charge.")
        elif column["notnull"] and column["default"] is None and not column["pk"]:
            blockers.append(
                f"{table}.{column['name']}: colonne cible obligatoire absente de la source."
            )
    return blockers


def _remove_column_from_create_sql(sql: str, column_name: str) -> str | None:
    """Remove exactly one top-level column declaration from CREATE TABLE SQL."""
    open_at = sql.find("(")
    if open_at < 0:
        return None
    depth = 0
    quote = None
    close_at = None
    i = open_at
    while i < len(sql):
        char = sql[i]
        if quote:
            if quote == "]":
                if char == "]":
                    quote = None
            elif char == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "[":
            quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_at = i
                break
        i += 1
    if close_at is None:
        return None

    body = sql[open_at + 1:close_at]
    parts = []
    start = 0
    depth = 0
    quote = None
    i = 0
    while i < len(body):
        char = body[i]
        if quote:
            if quote == "]":
                if char == "]":
                    quote = None
            elif char == quote:
                if i + 1 < len(body) and body[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "[":
            quote = "]"
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(body[start:i].strip())
            start = i + 1
        i += 1
    parts.append(body[start:].strip())

    kept = []
    removed = 0
    for part in parts:
        match = re.match(
            r'^\s*(?:"((?:""|[^"])*)"|\x60((?:\x60\x60|[^\x60])*)\x60|\[([^\]]+)\]|([A-Za-z_][A-Za-z0-9_]*))',
            part,
        )
        first = next((value for value in match.groups() if value is not None), "") if match else ""
        first = first.replace('""', '"').replace("``", "`")
        if first.casefold() == column_name.casefold():
            removed += 1
        else:
            kept.append(part)
    if removed != 1:
        return None
    normalized = " ".join(
        (sql[:open_at] + "(" + ", ".join(kept) + ")" + sql[close_at + 1:]).split()
    ).casefold()
    return normalized


def _fts_virtual_tables(connection: Any) -> list[str]:
    """Find FTS virtual tables before treating SQLite shadow tables as ordinary data."""
    rows = connection.execute(
        """
        SELECT name, sql FROM sqlite_master
        WHERE type='table' AND sql IS NOT NULL
        ORDER BY name
        """
    ).fetchall()
    return [
        str(_row_value(row, "name", 0))
        for row in rows
        if re.search(r"\bUSING\s+fts[345]\b", str(_row_value(row, "sql", 1) or ""), re.I)
    ]


def _table_definition_component_fingerprints(connection: Any, table: str) -> dict[str, Any]:
    """Hash semantic schema components without exposing SQL, defaults, or row data."""
    columns = connection.execute(
        f"PRAGMA table_xinfo({_quote_identifier(table)})"
    ).fetchall()
    column_signature = [
        (
            str(_row_value(row, "name", 1)),
            str(_row_value(row, "type", 2) or "").upper(),
            int(_row_value(row, "notnull", 3)),
            hashlib.sha256(str(_row_value(row, "dflt_value", 4)).encode("utf-8")).hexdigest()
                if _row_value(row, "dflt_value", 4) is not None else None,
            int(_row_value(row, "pk", 5)),
            int(_row_value(row, "hidden", 6)),
        )
        for row in columns
    ]
    objects = {item["name"]: item["sql"] for item in _objects(connection)}
    create_sql = objects.get(table) or ""
    advanced = sorted(set(re.findall(
        r"\b(AUTOINCREMENT|COLLATE|STRICT|WITHOUT\s+ROWID|ON\s+CONFLICT)\b",
        str(create_sql), re.I,
    )))

    def digest(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return {
        "columns_sha256": digest(column_signature),
        "foreign_keys_sha256": digest(_foreign_key_signature(connection, table)),
        "unique_constraints_sha256": digest(_unique_index_signature(connection, table)),
        "check_constraints_sha256": digest(_check_constraint_signature(create_sql)),
        "advanced_options": advanced,
    }


def build_data_migration_plan(source: Any, target: Any) -> dict[str, Any]:
    """Return a metadata-only migration preview; never select business rows."""
    # FTS virtual tables own implementation-specific shadow tables. Copying
    # those shadow tables as ordinary rows is unsafe; fail closed until a
    # dedicated rebuild strategy is implemented and verified for libSQL.
    source_fts = _fts_virtual_tables(source)
    target_fts = _fts_virtual_tables(target)
    if source_fts or target_fts:
        blockers = []
        if source_fts:
            blockers.append(
                "Tables FTS source détectées : " + ", ".join(source_fts)
                + ". Migration bloquée ; reconstruire les index FTS séparément."
            )
        if target_fts:
            blockers.append(
                "Tables FTS cible détectées : " + ", ".join(target_fts)
                + ". Migration bloquée ; vérifier/reconstruire les index FTS séparément."
            )
        return {
            "version": "50.64",
            "read_only": True,
            "data_contents_exposed": False,
            "ready": False,
            "schema_plan": None,
            "blockers": blockers,
            "tables": [],
        }

    # Always collect structural diagnostics, even when the additive schema
    # planner finds blockers. This remains metadata-only: no business rows are
    # selected or returned, and the report helps explain why preview is blocked.
    detailed = compare_database_inventories(
        inspect_database(source),
        inspect_database(target),
    ).get("detailed_audit", {})

    table_definition_diagnostics = {}
    for difference in detailed.get("differences", []):
        if difference.get("category") != "table_constraints_or_options":
            continue
        table = difference.get("table")
        if table:
            table_definition_diagnostics[table] = {
                "source": _table_definition_component_fingerprints(source, table),
                "target": _table_definition_component_fingerprints(target, table),
            }

    schema = build_migration_plan(source, target)
    if not schema.get("ready"):
        return {
            "version": "50.63",
            "read_only": True,
            "data_contents_exposed": False,
            "ready": False,
            "schema_plan": schema,
            "schema_diagnostics": detailed,
            "table_definition_diagnostics": table_definition_diagnostics,
            "blockers": list(schema.get("blockers", [])),
            "tables": [],
        }

    # The schema planner intentionally supports only reviewed additive changes.
    # Also consult the detailed audit for table-level options/generated-column
    # drift that a simple column comparison could otherwise miss.
    table_sql_blockers = []
    for difference in detailed.get("differences", []):
        if difference.get("category") != "table_constraints_or_options":
            continue
        table = difference.get("table")
        planned_rebuilds = {
            item.get("object")
            for item in (schema.get("statements") or [])
            if item.get("kind") == "rebuild_table"
        }
        if table in planned_rebuilds:
            # The schema planner has already checked the exact table-specific
            # rebuild allowlist, stable PK, FK dependencies, indexes and columns.
            continue
        # Allow only the exact, reviewed legacy skills.xp omission: removing
        # that one column declaration from the source SQL must reproduce the
        # target SQL byte-for-byte after whitespace normalization.
        if table == "skills":
            source_details = {c["name"]: c for c in _columns(source, table)}
            target_details = {c["name"]: c for c in _columns(target, table)}
            source_names = set(source_details)
            target_names = set(target_details)
            xp = source_details.get("xp", {})
            common_fields = ("type", "notnull", "default", "pk", "hidden")
            common_match = all(
                all(
                    source_details[name].get(field) == target_details[name].get(field)
                    for field in common_fields
                )
                for name in source_names & target_names
            )
            source_sql = next(
                (item["sql"] for item in _objects(source) if item["name"] == table),
                None,
            )
            target_sql = next(
                (item["sql"] for item in _objects(target) if item["name"] == table),
                None,
            )
            if (
                source_names - target_names == {"xp"}
                and not (target_names - source_names)
                and common_match
                and xp.get("type", "").upper() == "REAL"
                and xp.get("notnull") == 1
                and str(xp.get("default")) in {"0.0", "0"}
                and xp.get("pk") == 0
                and xp.get("hidden") == 0
                and source_sql
                and target_sql
                and _remove_column_from_create_sql(source_sql, "xp")
                    == " ".join(str(target_sql).split()).casefold()
            ):
                continue
        table_sql_blockers.append(
            f"{table}: définition SQL de table différente ; revue manuelle requise."
        )
    if table_sql_blockers:
        return {
            "version": "50.63",
            "read_only": True,
            "data_contents_exposed": False,
            "ready": False,
            "schema_plan": schema,
            # Preserve metadata-only comparison details so the compact report
            # can explain each SQL-definition blocker without exposing rows.
            "schema_diagnostics": detailed,
            "table_definition_diagnostics": table_definition_diagnostics,
            "blockers": table_sql_blockers,
            "tables": [],
        }

    source_tables = [item["name"] for item in _objects(source)]
    target_tables = {item["name"] for item in _objects(target)}
    blockers: list[str] = []
    table_reports = []
    for table in source_tables:
        source_columns = _columns(source, table)
        if table in target_tables:
            target_columns = _columns(target, table)
            blockers.extend(_preflight_extra_columns(source_columns, target_columns, table))
        source_count = int(source.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        ).fetchone()[0])
        target_count = (
            int(target.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()[0])
            if table in target_tables else 0
        )
        table_reports.append({
            "table": table,
            "source_rows": source_count,
            "target_rows_before": target_count,
            "primary_key": [
                column["name"] for column in sorted(
                    (c for c in source_columns if c["pk"]),
                    key=lambda c: c["pk"],
                )
            ],
        })

    try:
        ordered = _table_order(source, source_tables)
    except ValueError as exc:
        blockers.append(str(exc))
        ordered = []

    return {
        "version": "50.63",
        "read_only": True,
        "data_contents_exposed": False,
        "ready": not blockers,
        "schema_plan": schema,
        "blockers": blockers,
        "table_order": ordered,
        "tables": table_reports,
        "target_rows_are_preserved": True,
        "conflicting_rows": "abort_and_rollback",
    }


def summarize_data_migration_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, metadata-only migration report without SQL or row contents."""
    schema = plan.get("schema_plan") or {}
    diagnostics = plan.get("schema_diagnostics") or {}
    differences = diagnostics.get("differences") or []
    severity_counts = diagnostics.get("severity_counts") or {}

    by_category: dict[str, int] = {}
    for item in differences:
        category = str(item.get("category") or "other")
        by_category[category] = by_category.get(category, 0) + 1

    missing_tables = list(schema.get("missing_tables") or [])
    blockers = [str(item) for item in (plan.get("blockers") or [])]
    difference_preview = [
        {
            "severity": item.get("severity"),
            "category": item.get("category"),
            "table": item.get("table"),
            "item": item.get("item"),
            "message": item.get("message"),
        }
        for item in differences[:12]
    ]
    # Expose actionable schema metadata only. Never include SQL text, default
    # expressions, row values, or arbitrary driver objects in this compact view.
    definition_differences = []
    table_definition_diagnostics = plan.get("table_definition_diagnostics") or {}
    structural_differences = []
    for item in differences:
        category = item.get("category")
        table = item.get("table")
        if category == "table_constraints_or_options":
            source_sql = str(item.get("local") or "")
            target_sql = str(item.get("remote") or "")
            definition_differences.append({
                "table": table,
                "source_sha256": hashlib.sha256(source_sql.encode("utf-8")).hexdigest(),
                "target_sha256": hashlib.sha256(target_sql.encode("utf-8")).hexdigest(),
                "source_length": len(source_sql),
                "target_length": len(target_sql),
                "semantic_components": table_definition_diagnostics.get(table, {}),
                "requires_manual_review": True,
            })
            continue
        if category not in {
            "missing_column", "extra_column", "column_definition",
            "foreign_keys", "missing_unique_constraint",
            "extra_unique_constraint", "missing_index", "extra_index",
            "unique_constraint_definition", "index_definition",
        }:
            continue

        def safe_metadata(value: Any) -> Any:
            if not isinstance(value, dict):
                return None
            allowed = (
                "name", "type", "notnull", "primary_key_position",
                "generated_or_hidden", "metadata_complete", "hidden",
                "referenced_table", "from_column", "to_column",
                "on_update", "on_delete", "match", "sequence", "id",
                "unique", "origin", "partial",
            )
            result = {key: value[key] for key in allowed if key in value}
            if isinstance(value.get("columns"), list):
                result["columns"] = [
                    {
                        key: column.get(key)
                        for key in ("name", "sequence", "descending", "key_column")
                        if key in column
                    }
                    for column in value["columns"] if isinstance(column, dict)
                ]
            return result

        structural_differences.append({
            "category": category,
            "table": table,
            "item": item.get("item"),
            "source": safe_metadata(item.get("local")),
            "target": safe_metadata(item.get("remote")),
            "explanation": item.get("explanation"),
        })
    return {
        "version": plan.get("version", "50.64"),
        "read_only": True,
        "data_contents_exposed": False,
        "migration_executed": False,
        "ready": bool(plan.get("ready")),
        "source_database": "SQLite local",
        "target_database": "Turso",
        "schema": {
            "source_table_count": schema.get("source_table_count"),
            "target_table_count": schema.get("target_table_count"),
            "missing_table_count": len(missing_tables),
            "missing_tables": missing_tables[:30],
            "missing_tables_truncated": len(missing_tables) > 30,
        },
        "counts": {
            "blockers": len(blockers),
            "differences": len(differences),
            "differences_by_severity": severity_counts,
            "differences_by_category": by_category,
        },
        "blockers_preview": blockers[:12],
        "blockers_truncated": len(blockers) > 12,
        "differences_preview": difference_preview,
        "differences_truncated": len(differences) > len(difference_preview),
        "table_definition_differences": definition_differences[:10],
        "table_definition_differences_truncated": len(definition_differences) > 10,
        "structural_differences": structural_differences[:100],
        "structural_differences_truncated": len(structural_differences) > 100,
        "notes": [
            "Rapport compact : métadonnées de schéma autorisées uniquement ; aucun SQL brut, valeur par défaut ni contenu métier n'est exposé.",
            "Les différences de volumes de lignes ne sont pas détaillées dans cette vue.",
            "Aucune migration ni écriture en base n'a été exécutée.",
        ],
    }


def migrate_sqlite_rows_to_turso(
    source: Any,
    target: Any,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview by default; copy all source rows only with explicit apply=True."""
    plan = build_data_migration_plan(source, target)
    if not plan["ready"]:
        return {
            "version": "50.63",
            "applied": False,
            "ready": False,
            "read_only": True,
            "data_contents_exposed": False,
            "blockers": plan["blockers"],
            "table_count": len(plan["tables"]),
        }
    if not apply:
        return {
            "version": "50.63",
            "applied": False,
            "ready": True,
            "read_only": True,
            "data_contents_exposed": False,
            "table_count": len(plan["tables"]),
            "tables": plan["tables"],
            "schema_statement_count": plan["schema_plan"]["planned_statement_count"],
        }

    digest = hashlib.sha256()
    table_results = []
    inserted_total = 0
    already_present_total = 0
    target.execute("BEGIN")
    try:
        for statement in plan["schema_plan"]["statements"]:
            apply_schema_statement(target, statement)

        for table in plan["table_order"]:
            source_columns = _columns(source, table)
            target_columns = _columns(target, table)
            if any(column["hidden"] == 1 for column in source_columns):
                raise ValueError(
                    f"Table virtuelle non prise en charge pour migration sûre : {table}."
                )
            selectable_columns = [column for column in source_columns if column["hidden"] != 1]
            names = [column["name"] for column in selectable_columns]
            insertable = [column for column in source_columns if column["hidden"] == 0]
            insert_names = [column["name"] for column in insertable]
            primary_keys = [
                column["name"] for column in sorted(
                    (c for c in source_columns if c["pk"]),
                    key=lambda c: c["pk"],
                )
            ]
            cursor = source.execute(
                f"SELECT * FROM {_quote_identifier(table)} ORDER BY " +
                ", ".join(_quote_identifier(name) for name in primary_keys or names)
            )
            placeholders = ",".join("?" for _ in insert_names)
            columns_sql = ",".join(_quote_identifier(name) for name in insert_names)
            insert_sql = (
                f"INSERT INTO {_quote_identifier(table)} ({columns_sql}) "
                f"VALUES ({placeholders})"
            )
            inserted = 0
            already_present = 0
            seen_without_pk: dict[str, int] = {}
            table_digest = hashlib.sha256()
            verified_digest = hashlib.sha256()
            while True:
                batch = cursor.fetchmany(200)
                if not batch:
                    break
                for raw_row in batch:
                    values = tuple(raw_row)
                    _row_digest_update(table_digest, table, names, values)
                    if primary_keys:
                        exists, existing = _row_exists(
                            target, table, names, values, primary_keys
                        )
                        if exists:
                            if existing != values:
                                raise ValueError(
                                    f"Collision de clé dans {table}; aucune ligne n'a été validée."
                                )
                            already_present += 1
                            verified_values = existing
                        else:
                            insert_values = tuple(
                                values[names.index(name)] for name in insert_names
                            )
                            target.execute(insert_sql, insert_values)
                            inserted += 1
                            found, verified_values = _row_exists(
                                target, table, names, values, primary_keys
                            )
                            if not found or verified_values != values:
                                raise ValueError(
                                    f"Relecture après insertion échouée pour {table}."
                                )
                    else:
                        identity = json.dumps(
                            [_normalize(value) for value in values],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        occurrence = seen_without_pk.get(identity, 0) + 1
                        seen_without_pk[identity] = occurrence
                        matching_rows = _row_match_count(
                            target, table, names, values
                        )
                        if matching_rows >= occurrence:
                            already_present += 1
                            verified_values = values
                        else:
                            insert_values = tuple(
                                values[names.index(name)] for name in insert_names
                            )
                            target.execute(insert_sql, insert_values)
                            inserted += 1
                            if _row_match_count(target, table, names, values) < occurrence:
                                raise ValueError(
                                    f"Relecture après insertion échouée pour {table}."
                                )
                            verified_values = values
                    _row_digest_update(
                        verified_digest, table, names, verified_values
                    )
            if table_digest.digest() != verified_digest.digest():
                raise ValueError(f"Empreinte de données différente pour {table}.")
            expected_count = int(source.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()[0])
            verified_count = inserted + already_present
            if verified_count != expected_count:
                raise ValueError(
                    f"Vérification de volume échouée pour {table}."
                )
            target_count = int(target.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()[0])
            table_results.append({
                "table": table,
                "source_rows": expected_count,
                "inserted_rows": inserted,
                "already_present_rows": already_present,
                "target_rows_after": target_count,
                "source_sha256": table_digest.hexdigest(),
            })
            inserted_total += inserted
            already_present_total += already_present

        fk_rows = target.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise ValueError(
                f"Vérification des clés étrangères échouée ({len(fk_rows)} violation(s))."
            )

        # Durable proof that this exact migration flow completed. The app
        # refuses to start on Turso unless this marker exists.
        target.execute(
            """
            CREATE TABLE IF NOT EXISTS chappie_storage_migrations (
                migration_key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                source_table_count INTEGER NOT NULL,
                source_row_count INTEGER NOT NULL,
                inserted_rows INTEGER NOT NULL,
                already_present_rows INTEGER NOT NULL,
                completed_at TEXT NOT NULL
            )
            """
        )
        target.execute(
            """
            INSERT OR REPLACE INTO chappie_storage_migrations (
                migration_key, status, source_table_count, source_row_count,
                inserted_rows, already_present_rows, completed_at
            ) VALUES (?, 'completed', ?, ?, ?, ?, ?)
            """,
            (
                "sqlite-to-turso-v50.64",
                len(table_results),
                sum(item["source_rows"] for item in table_results),
                inserted_total,
                already_present_total,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        target.commit()
    except Exception:
        target.rollback()
        raise

    return {
        "version": "50.63",
        "applied": True,
        "ready": True,
        "read_only": False,
        "data_contents_exposed": False,
        "inserted_rows": inserted_total,
        "already_present_rows": already_present_total,
        "tables": table_results,
        "foreign_key_violations": 0,
        "target_rows_are_preserved": True,
        "transaction": "committed",
    }
