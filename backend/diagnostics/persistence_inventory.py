"""Authenticated production-safe SQLite inventory helpers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bytes):
        return {
            "type": "blob",
            "sha256": hashlib.sha256(value).hexdigest(),
            "length": len(value),
        }
    if isinstance(value, bool):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "real", "value": repr(value)}
    return {"type": "text", "value": str(value)}


def inspect_sqlite_database(database_path: str | Path) -> dict[str, Any]:
    """Inspect one explicit SQLite file without exposing row values or writing."""
    path = Path(database_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("The supplied database path is not a regular file")

    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=10
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("BEGIN")

        integrity_values = [
            str(row[0])
            for row in connection.execute("PRAGMA integrity_check").fetchall()
        ]
        integrity_ok = integrity_values == ["ok"]

        schema_rows = connection.execute(
            """
            SELECT type, name, tbl_name, COALESCE(sql, '')
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name, tbl_name
            """
        ).fetchall()
        schema_objects = [
            {
                "type": str(row[0]),
                "name": str(row[1]),
                "table": str(row[2]),
                "sql_sha256": hashlib.sha256(
                    str(row[3]).encode("utf-8")
                ).hexdigest(),
            }
            for row in schema_rows
        ]
        schema_payload = json.dumps(
            schema_objects, sort_keys=True, separators=(",", ":")
        )
        schema_sha256 = hashlib.sha256(
            schema_payload.encode("utf-8")
        ).hexdigest()

        table_names = [
            item["name"] for item in schema_objects if item["type"] == "table"
        ]
        table_reports: list[dict[str, Any]] = []
        for table in table_names:
            quoted = _quote_identifier(table)
            columns = [
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({quoted})"
                ).fetchall()
            ]
            cursor = connection.execute(f"SELECT * FROM {quoted}")
            row_digests: list[str] = []
            for row in cursor:
                canonical_row = [
                    _canonical_value(row[column]) for column in columns
                ]
                encoded = json.dumps(
                    canonical_row,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                row_digests.append(hashlib.sha256(encoded).hexdigest())
            row_digests.sort()
            table_reports.append(
                {
                    "table": table,
                    "row_count": len(row_digests),
                    "content_sha256": hashlib.sha256(
                        "".join(row_digests).encode("ascii")
                    ).hexdigest(),
                }
            )

        return {
            "audit": "V50.49",
            "read_only": True,
            "database_contents_exposed": False,
            "database_name": path.name,
            "database_size_bytes": path.stat().st_size,
            "integrity_check": {
                "ok": integrity_ok,
                "issue_count": 0 if integrity_ok else len(integrity_values),
            },
            "schema_object_count": len(schema_objects),
            "schema_sha256": schema_sha256,
            "tables": table_reports,
            "total_rows": sum(item["row_count"] for item in table_reports),
        }
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
