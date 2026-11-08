#!/usr/bin/env python3
"""Static inventory of SQLite/libSQL-sensitive Python usage in backend source.

This is a review aid, not a proof of remote compatibility. It performs no DB
connection and never reads environment variables or secrets.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "backend"

CALL_RULES = {
    "sqlite_connect": {"connect"},
    "script_execution": {"executescript"},
    "native_backup": {"backup"},
    "row_factory": {"row_factory"},
    "cursor_metadata": {"lastrowid", "rowcount", "total_changes", "in_transaction"},
    "custom_sql_functions": {"create_function", "create_aggregate", "create_window_function", "create_collation"},
    "connection_configuration": {"set_trace_callback", "set_authorizer", "set_progress_handler"},
    "transaction_control": {"commit", "rollback"},
}
SQL_RULES = {
    "pragma": ("PRAGMA ",),
    "replace_or_ignore": ("INSERT OR REPLACE", "INSERT OR IGNORE", "REPLACE INTO"),
    "sqlite_upsert": ("ON CONFLICT",),
    "returning": (" RETURNING ",),
    "json_functions": ("JSON_EXTRACT", "JSON_SET", "JSON_OBJECT", "JSON_ARRAY", "JSON_VALID"),
    "date_time_functions": ("DATETIME(", "JULIANDAY(", "STRFTIME(", "UNIXEPOCH("),
    "sqlite_specific_functions": ("TOTAL(", "CHANGES(", "LAST_INSERT_ROWID(", "ZEROBLOB("),
    "fts_or_virtual_tables": ("VIRTUAL TABLE", "FTS5", "RTREE"),
    "trigger_ddl": ("CREATE TRIGGER",),
    "index_ddl": ("CREATE INDEX", "CREATE UNIQUE INDEX"),
    "foreign_key_ddl": ("FOREIGN KEY", "REFERENCES "),
    "check_constraints": (" CHECK ",),
    "autoincrement": ("AUTOINCREMENT",),
}
EXCLUDED_PARTS = {".git", "__pycache__", ".venv", "venv"}


def python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if not any(part in EXCLUDED_PARTS for part in path.parts):
            yield path


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def scan_file(path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [{
            "category": "parse_error",
            "line": exc.lineno or 1,
            "symbol": "python",
            "snippet": str(exc),
        }]

    findings: list[dict] = []
    rel = path.relative_to(ROOT).as_posix()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            leaf = name.rsplit(".", 1)[-1]
            for category, leaves in CALL_RULES.items():
                if leaf in leaves:
                    findings.append({
                        "category": category,
                        "line": node.lineno,
                        "symbol": name,
                        "snippet": ast.get_source_segment(source, node.func) or name,
                    })
            # sqlite3.Row, sqlite3.Connection and sqlite3.Error assumptions
            if leaf in {"Row", "Connection", "Error", "IntegrityError", "OperationalError", "ProgrammingError"} and "sqlite3" in name:
                findings.append({
                    "category": "sqlite_type_or_exception",
                    "line": node.lineno,
                    "symbol": name,
                    "snippet": name,
                })

        if isinstance(node, ast.Attribute):
            name = dotted_name(node)
            leaf = node.attr
            if leaf in {"isolation_level", "text_factory", "row_factory"}:
                findings.append({
                    "category": "connection_configuration",
                    "line": node.lineno,
                    "symbol": name,
                    "snippet": name,
                })

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = " " + " ".join(node.value.upper().split()) + " "
            for category, needles in SQL_RULES.items():
                if any(needle in upper for needle in needles):
                    findings.append({
                        "category": category,
                        "line": node.lineno,
                        "symbol": "SQL literal",
                        "snippet": " ".join(node.value.strip().split())[:180],
                    })

    unique = {
        (f["category"], f["line"], f["symbol"], f["snippet"]): f
        for f in findings
    }
    return [
        {"path": rel, **finding}
        for finding in sorted(unique.values(), key=lambda x: (x["line"], x["category"], x["symbol"]))
    ]


def build_report(root: Path = SOURCE_ROOT) -> dict:
    findings = []
    files_scanned = 0
    for path in python_files(root):
        files_scanned += 1
        findings.extend(scan_file(path))
    categories: dict[str, int] = {}
    for finding in findings:
        categories[finding["category"]] = categories.get(finding["category"], 0) + 1
    return {
        "audit": "V50.42",
        "static_only": True,
        "database_connections_opened": 0,
        "secrets_read": False,
        "files_scanned": files_scanned,
        "finding_count": len(findings),
        "categories": dict(sorted(categories.items())),
        "findings": sorted(findings, key=lambda x: (x["path"], x["line"], x["category"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
