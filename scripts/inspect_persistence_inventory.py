#!/usr/bin/env python3
"""Read-only SQLite inventory: schema, row counts and content fingerprints.

No row values, prompts, memories, credentials or environment variables are
written to the report. A database path must be supplied explicitly.
"""
from __future__ import annotations

import argparse
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
        return {"type": "blob", "sha256": hashlib.sha256(value).hexdigest(),
                "length": len(value)}
    if isinstance(value, bool):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "real", "value": repr(value)}
    return {"type": "text", "value": str(value)}


def _schema_inventory(connection: sqlite3.Connection) -> tuple[list[dict], str]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    objects = [
        {"type": str(row[0]), "name": str(row[1]),
         "table": str(row[2]), "sql_sha256": hashlib.sha256(
             str(row[3]).encode("utf-8")
         ).hexdigest()}
        for row in rows
    ]
    canonical = json.dumps(objects, sort_keys=True, separators=(",", ":"))
    return objects, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_sqlite_database(database_path: str | Path) -> dict[str, Any]:
    path = Path(database_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("The supplied database path is not a regular file")

    uri = path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity_values = [str(row[0]) for row in integrity_rows]
        integrity_ok = integrity_values == ["ok"]

        objects, schema_sha256 = _schema_inventory(connection)
        tables = [
            item["name"] for item in objects if item["type"] == "table"
        ]
        table_reports: list[dict[str, Any]] = []

        for table in tables:
            quoted = _quote_identifier(table)
            row_count = int(connection.execute(
                f"SELECT COUNT(*) FROM {quoted}"
            ).fetchone()[0])
            column_names = [
                str(row[1]) for row in connection.execute(
                    f"PRAGMA table_info({quoted})"
                ).fetchall()
            ]
            row_digests: list[str] = []
            cursor = connection.execute(f"SELECT * FROM {quoted}")
            for row in cursor:
                canonical_row = [
                    _canonical_value(row[column]) for column in column_names
                ]
                encoded = json.dumps(
                    canonical_row, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":")
                ).encode("utf-8")
                row_digests.append(hashlib.sha256(encoded).hexdigest())
            row_digests.sort()
            table_reports.append({
                "table": table,
                "row_count": row_count,
                "content_sha256": hashlib.sha256(
                    "".join(row_digests).encode("ascii")
                ).hexdigest(),
            })

        return {
            "audit": "V50.48",
            "read_only": True,
            "database_contents_exposed": False,
            "database_name": path.name,
            "database_size_bytes": path.stat().st_size,
            "integrity_check": {
                "ok": integrity_ok,
                "issue_count": 0 if integrity_ok else len(integrity_values),
            },
            "schema_object_count": len(objects),
            "schema_sha256": schema_sha256,
            "tables": table_reports,
            "total_rows": sum(item["row_count"] for item in table_reports),
        }
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", required=True, type=Path,
        help="Exact SQLite file to inspect (opened read-only)."
    )
    parser.add_argument(
        "--output", type=Path,
        help="Optional JSON report path; never write it inside the database file."
    )
    args = parser.parse_args()
    report = inspect_sqlite_database(args.database)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["integrity_check"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
