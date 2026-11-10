"""Plan and apply additive SQLite -> libSQL schema migrations safely.

The default operation is planning only. Applying changes requires an explicit
apply=True argument from a deliberate caller. Existing rows are never copied,
updated, or deleted by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
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
          AND name != 'chappie_storage_migration_state'
          AND name NOT LIKE 'chappie_migration_guard_%'
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



def _index_is_unique(connection: Any, table_name: str, index_name: str) -> bool | None:
    """Return index uniqueness, or None when metadata cannot prove it."""
    rows = connection.execute(
        f"PRAGMA index_list({_quote_identifier(table_name)})"
    ).fetchall()
    for row in rows:
        if str(_row_value(row, "name", 1)) == index_name:
            return bool(_row_value(row, "unique", 2))
    return None



REBUILDABLE_TABLES = {"conversations", "memories", "skills"}


def _rebuild_table_spec(
    source: Any,
    target: Any,
    table_name: str,
    source_sql: str,
    target_sql: str,
    source_objects: dict[str, dict[str, Any]],
    target_objects: dict[str, dict[str, Any]],
    additive_columns: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Prove a narrow, lossless rebuild is possible before planning it."""
    blockers: list[str] = []
    if table_name not in REBUILDABLE_TABLES:
        return None, [f"{table_name}: reconstruction automatique non autorisée."]

    source_columns = source.execute(
        f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
    ).fetchall()
    target_columns = target.execute(
        f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
    ).fetchall()
    if not source_columns or not target_columns:
        return None, [f"{table_name}: métadonnées de colonnes incomplètes."]

    def column_map(rows: list[Any]) -> dict[str, tuple[Any, ...]]:
        result = {}
        for row in rows:
            name = str(_row_value(row, "name", 1))
            result[name] = (
                str(_row_value(row, "type", 2) or "").upper(),
                int(_row_value(row, "notnull", 3)),
                str(_row_value(row, "dflt_value", 4)),
                int(_row_value(row, "pk", 5)),
                int(_row_value(row, "hidden", 6)),
            )
        return result

    source_map = column_map(source_columns)
    target_map = column_map(target_columns)
    additive_columns = additive_columns or {}
    missing_in_target = set(source_map) - set(target_map)
    unexpected_in_target = set(target_map) - set(source_map)
    if unexpected_in_target:
        blockers.append(
            f"{table_name}: colonnes supplémentaires côté cible non prises en charge : "
            + ", ".join(sorted(unexpected_in_target)) + "."
        )
    for name in sorted(missing_in_target):
        declaration = " ".join(str(additive_columns.get(name, "")).upper().split())
        metadata = source_map[name]
        # Only explicitly allowlisted, ordinary columns with a matching
        # source definition may be introduced during a verified rebuild.
        match = re.fullmatch(
            r"([A-Z][A-Z0-9_]*(?:\s*\([^)]*\))?)(?:\s+(NOT NULL))?(?:\s+DEFAULT\s+(.+))?",
            declaration,
        )
        if (
            not match
            or metadata[0] != match.group(1)
            or metadata[1] != int(bool(match.group(2)))
            or _normalized_sql(metadata[2]) != _normalized_sql(match.group(3))
            or metadata[3] != 0
            or metadata[4] != 0
        ):
            blockers.append(
                f"{table_name}.{name}: ajout pendant reconstruction non autorisé ou définition source incohérente."
            )
    if any(item[4] != 0 for item in source_map.values()) or any(
        item[4] != 0 for item in target_map.values()
    ):
        blockers.append(f"{table_name}: colonne générée/cachée non prise en charge.")
    source_pk = [name for name, meta in sorted(source_map.items(), key=lambda pair: pair[1][3]) if meta[3]]
    target_pk = [name for name, meta in sorted(target_map.items(), key=lambda pair: pair[1][3]) if meta[3]]
    if not source_pk or source_pk != target_pk:
        blockers.append(f"{table_name}: clé primaire stable identique non démontrée.")

    for name in sorted(set(source_map) & set(target_map)):
        if source_map[name] == target_map[name]:
            continue
        if table_name == "skills" and name == "level":
            # Only the declared storage type may differ; nullability, default,
            # PK position and hidden/generated status must remain identical.
            if (
                source_map[name][1] == target_map[name][1]
                and source_map[name][3] == target_map[name][3]
                and source_map[name][4] == target_map[name][4]
            ):
                continue
        blockers.append(f"{table_name}.{name}: différence non autorisée pour reconstruction.")

    if _foreign_key_signature(source, table_name) != _foreign_key_signature(target, table_name):
        blockers.append(f"{table_name}: clés étrangères différentes.")
    if _unique_index_signature(source, table_name) != _unique_index_signature(target, table_name):
        blockers.append(f"{table_name}: contraintes UNIQUE différentes.")

    # Only target-side dependencies can be damaged by rebuilding the target.
    # Source-only child tables are created before rebuild statements and are
    # empty at this stage. Existing target child tables are safe only when
    # empty; otherwise DROP TABLE could invalidate their foreign keys.
    table_rows = target.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for row in table_rows:
        other = str(_row_value(row, "name", 0))
        if other == table_name:
            continue
        foreign_keys = target.execute(
            f"PRAGMA foreign_key_list({_quote_identifier(other)})"
        ).fetchall()
        if any(str(_row_value(fk, "table", 2)) == table_name for fk in foreign_keys):
            dependent_count = int(target.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(other)}"
            ).fetchone()[0])
            if dependent_count:
                blockers.append(
                    f"{table_name}: référencée par une clé étrangère de {other} "
                    "(cible non vide), reconstruction refusée."
                )

    for connection, label in ((source, "source"), (target, "cible")):
        trigger_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (table_name,),
        ).fetchall()
        if trigger_rows:
            blockers.append(f"{table_name}: déclencheur SQL présent ({label}).")
        view_rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='view' AND sql IS NOT NULL"
        ).fetchall()
        for view in view_rows:
            view_name = str(_row_value(view, "name", 0))
            view_sql = str(_row_value(view, "sql", 1) or "")
            if re.search(rf"(?i)(?<![A-Za-z0-9_]){re.escape(table_name)}(?![A-Za-z0-9_])", view_sql):
                blockers.append(f"{table_name}: vue dépendante détectée ({view_name}, {label}).")

    if "AUTOINCREMENT" in source_sql.upper() or "AUTOINCREMENT" in target_sql.upper():
        blockers.append(f"{table_name}: séquence AUTOINCREMENT non prise en charge par reconstruction.")
    unsupported_sql = re.compile(r"\b(?:COLLATE|STRICT|WITHOUT\s+ROWID|ON\s+CONFLICT)\b", re.I)
    for label, sql in (("source", source_sql), ("cible", target_sql)):
        if unsupported_sql.search(sql):
            blockers.append(
                f"{table_name}: option ou clause SQL avancée non prise en charge ({label})."
            )

    temp_name = f"__chappie_rebuild_{table_name}"
    if target.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? LIMIT 1", (temp_name,)
    ).fetchone():
        blockers.append(f"{table_name}: table temporaire de reconstruction déjà présente.")

    match = re.match(
        r'(?is)^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)'
        r'(?:"(?:[^"]|"")*"|\x60(?:[^\x60]|\x60\x60)*\x60|\[[^\]]+\]|[^\s(]+)',
        source_sql,
    )
    if not match:
        blockers.append(f"{table_name}: CREATE TABLE source non reconnu.")
    if blockers:
        return None, sorted(set(blockers))

    create_sql = (
        match.group(1) + _quote_identifier(temp_name) + source_sql[match.end():]
    )
    # Copy only columns already present on the target. Any allowlisted
    # source-only columns are introduced by the canonical CREATE TABLE and
    # receive their declared safe default; source rows are copied later.
    columns = sorted(set(source_map) & set(target_map), key=lambda name: next(
        int(_row_value(row, "cid", 0)) for row in source_columns
        if str(_row_value(row, "name", 1)) == name
    ))
    indexes = [
        str(item["sql"])
        for item in source_objects.values()
        if item["type"] == "index" and item["table"] == table_name and item["sql"]
    ]
    return {
        "kind": "rebuild_table",
        "object": table_name,
        "table": table_name,
        "temporary_table": temp_name,
        "create_sql": create_sql,
        "columns": columns,
        "primary_key": source_pk,
        "indexes": sorted(indexes),
    }, []


def _digest_table_rows(connection: Any, table_name: str, columns: list[str], primary_key: list[str]) -> tuple[int, str]:
    selected = ", ".join(_quote_identifier(name) for name in columns)
    order = ", ".join(_quote_identifier(name) for name in primary_key)
    cursor = connection.execute(
        f"SELECT {selected} FROM {_quote_identifier(table_name)} ORDER BY {order}"
    )
    digest = hashlib.sha256()
    count = 0
    while True:
        batch = cursor.fetchmany(200)
        if not batch:
            break
        for row in batch:
            values = []
            for value in tuple(row):
                if isinstance(value, (bytes, bytearray, memoryview)):
                    values.append({"blob": bytes(value).hex()})
                elif isinstance(value, int) and not isinstance(value, bool):
                    values.append({"number": str(value)})
                elif isinstance(value, float):
                    values.append({"number": format(value, ".17g")})
                elif value is None or isinstance(value, (str, bool)):
                    values.append(value)
                else:
                    values.append({"type": type(value).__name__, "value": str(value)})
            digest.update(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\\n")
            count += 1
    return count, digest.hexdigest()


def apply_schema_statement(target: Any, statement: dict[str, Any]) -> None:
    """Apply one reviewed schema statement inside the caller's transaction."""
    if statement.get("kind") != "rebuild_table":
        target.execute(statement["sql"])
        return

    table = statement["table"]
    temporary = statement["temporary_table"]
    columns = statement["columns"]
    primary_key = statement["primary_key"]
    quoted_columns = ", ".join(_quote_identifier(name) for name in columns)
    before_count, before_digest = _digest_table_rows(
        target, table, columns, primary_key
    )
    target.execute(statement["create_sql"])
    target.execute(
        f"INSERT INTO {_quote_identifier(temporary)} ({quoted_columns}) "
        f"SELECT {quoted_columns} FROM {_quote_identifier(table)}"
    )
    copied_count, copied_digest = _digest_table_rows(
        target, temporary, columns, primary_key
    )
    if (copied_count, copied_digest) != (before_count, before_digest):
        raise ValueError(
            f"{table}: vérification avant remplacement échouée; transaction annulée."
        )

    target.execute(f"DROP TABLE {_quote_identifier(table)}")
    target.execute(
        f"ALTER TABLE {_quote_identifier(temporary)} RENAME TO {_quote_identifier(table)}"
    )
    for index_sql in statement["indexes"]:
        target.execute(index_sql)

    after_count, after_digest = _digest_table_rows(
        target, table, columns, primary_key
    )
    if (after_count, after_digest) != (before_count, before_digest):
        raise ValueError(
            f"{table}: vérification après remplacement échouée; transaction annulée."
        )



def _unique_index_signature(connection: Any, table_name: str) -> list[tuple[Any, ...]]:
    """Return unique-index semantics, including UNIQUE table/column constraints."""
    indexes = connection.execute(
        f"PRAGMA index_list({_quote_identifier(table_name)})"
    ).fetchall()
    signature = []
    for row in indexes:
        if not int(_row_value(row, "unique", 2)):
            continue
        name = str(_row_value(row, "name", 1))
        origin = str(_row_value(row, "origin", 3))
        partial = int(_row_value(row, "partial", 4))
        columns = connection.execute(
            f"PRAGMA index_xinfo({_quote_identifier(name)})"
        ).fetchall()
        key_columns = tuple(
            (
                _row_value(column, "name", 2),
                int(_row_value(column, "desc", 3)),
                str(_row_value(column, "coll", 4) or "").casefold(),
            )
            for column in columns
            if int(_row_value(column, "key", 5))
        )
        signature.append((origin, partial, key_columns))
    return sorted(signature, key=repr)


def _check_constraint_signature(sql: Any) -> list[str] | None:
    """Extract CHECK clauses without depending on column declaration order."""
    if not sql:
        return None
    text = str(sql)
    open_at = text.find("(")
    if open_at < 0:
        return None
    body_end = len(text) - 1
    body = text[open_at + 1:body_end]
    backtick = chr(96)
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(body):
        char = body[i]
        if quote:
            if quote == "]":
                if char == "]":
                    if i + 1 < len(body) and body[i + 1] == "]":
                        i += 1
                    else:
                        quote = None
            elif char == quote:
                if i + 1 < len(body) and body[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in ("'", '"', backtick):
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
    if quote or depth != 0:
        return None
    parts.append(body[start:].strip())

    checks: list[str] = []
    for part in parts:
        lowered = part.casefold()
        if lowered.startswith("check") or lowered.startswith("constraint"):
            if "check" in lowered:
                checks.append(_normalized_sql(part))
            continue
        # Extract inline CHECK(...) expressions from column declarations.
        quote = None
        i = 0
        while i < len(part):
            char = part[i]
            if quote:
                if quote == "]":
                    if char == "]":
                        quote = None
                elif char == quote:
                    quote = None
            elif char in ("'", '"', backtick):
                quote = char
            elif char == "[":
                quote = "]"
            elif part[i:i + 5].casefold() == "check" and (
                i == 0 or not (part[i - 1].isalnum() or part[i - 1] == "_")
            ):
                j = i + 5
                while j < len(part) and part[j].isspace():
                    j += 1
                if j >= len(part) or part[j] != "(":
                    i += 5
                    continue
                check_start = j
                check_depth = 0
                check_quote = None
                while j < len(part):
                    current = part[j]
                    if check_quote:
                        if current == check_quote:
                            if j + 1 < len(part) and part[j + 1] == check_quote:
                                j += 1
                            else:
                                check_quote = None
                    elif current in ("'", '"', backtick):
                        check_quote = current
                    elif current == "(":
                        check_depth += 1
                    elif current == ")":
                        check_depth -= 1
                        if check_depth == 0:
                            checks.append(_normalized_sql(part[i: j + 1]))
                            break
                    j += 1
                if check_depth != 0:
                    return None
                i = j
            i += 1
    return sorted(checks)



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

    rebuild_tables: set[str] = set()

    for table_name in sorted(set(source_tables) & set(target_tables)):
        source_columns = _table_columns(source, table_name)
        target_columns = _table_columns(target, table_name)
        source_checks = _check_constraint_signature(source_tables[table_name]["sql"])
        target_checks = _check_constraint_signature(target_tables[table_name]["sql"])
        column_drift = {
            name for name in set(source_columns) & set(target_columns)
            if source_columns[name] != target_columns[name]
        }
        check_drift = source_checks != target_checks
        approved_rebuild = (
            table_name in REBUILDABLE_TABLES
            and (
                (table_name in {"conversations", "memories"} and check_drift and not column_drift)
                or (table_name == "skills" and column_drift == {"level"} and not check_drift)
            )
        )

        if source_checks is None or target_checks is None:
            blockers.append(f"{table_name}: contraintes CHECK impossibles à comparer de façon sûre.")
        elif check_drift and not approved_rebuild:
            blockers.append(f"{table_name}: contraintes CHECK différentes.")
        if column_drift and not approved_rebuild:
            for column_name in sorted(column_drift):
                blockers.append(
                    f"{table_name}.{column_name}: définition différente entre source et cible."
                )

        if _foreign_key_signature(source, table_name) != _foreign_key_signature(target, table_name):
            blockers.append(f"{table_name}: contraintes de clés étrangères différentes.")
        if _unique_index_signature(source, table_name) != _unique_index_signature(target, table_name):
            blockers.append(f"{table_name}: contraintes ou index UNIQUE différents.")

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

        if approved_rebuild:
            spec, rebuild_blockers = _rebuild_table_spec(
                source, target, table_name,
                str(source_tables[table_name]["sql"] or ""),
                str(target_tables[table_name]["sql"] or ""),
                source_objects, target_objects,
                allowed.get(table_name, {}),
            )
            blockers.extend(rebuild_blockers)
            if spec:
                statements.append(spec)
                rebuild_tables.add(table_name)
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
                if item["type"] == "index" and item["table"] in rebuild_tables:
                    continue
                if _normalized_sql(item["sql"]) != _normalized_sql(existing["sql"]):
                    if item["type"] == "index" and item["sql"] and existing["sql"]:
                        source_unique = _index_is_unique(
                            source, item["table"], item["name"]
                        )
                        target_unique = _index_is_unique(
                            target, existing["table"], existing["name"]
                        )
                        if (
                            source_unique is False
                            and target_unique is False
                            and item["table"] == existing["table"]
                        ):
                            statements.append({
                                "kind": "drop_index",
                                "object": item["name"],
                                "sql": f"DROP INDEX {_quote_identifier(item['name'])}",
                            })
                            statements.append({
                                "kind": "create_index",
                                "object": item["name"],
                                "sql": str(item["sql"]),
                            })
                        else:
                            blockers.append(
                                f"{item['type']} {item['name']}: définition différente "
                                "et remplacement automatique non prouvé sûr."
                            )
                    else:
                        blockers.append(
                            f"{item['type']} {item['name']}: définition différente entre source et cible."
                        )
            continue
        if item["type"] == "table":
            continue
        if item["type"] == "index":
            if item["table"] in rebuild_tables:
                continue
            if not item["sql"]:
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
    order = {"drop_index": 0, "create_table": 1, "add_column": 2, "rebuild_table": 3, "create_index": 4}
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
            apply_schema_statement(target, statement)
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
