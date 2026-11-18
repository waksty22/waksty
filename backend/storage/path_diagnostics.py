"""Read-only diagnostics for the exact SQLite database connection in use."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


def _row_value(row: Any, index: int) -> Any:
    try:
        return row[index]
    except (TypeError, KeyError, IndexError):
        return None


def _file_metadata(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "exists": True,
            "is_file": path.is_file(),
            "size_bytes": stat.st_size if path.is_file() else None,
        }
    except OSError:
        return {"exists": False, "is_file": False, "size_bytes": None}


def _unescape_mount_field(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _matching_mount(path: Path) -> dict[str, Any] | None:
    """Return the most specific Linux mount containing path, if available."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return None

    resolved = str(path.resolve(strict=False))
    matches: list[tuple[int, str, str]] = []
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left = before.split()
        right = after.split()
        if len(left) < 5 or not right:
            continue
        mountpoint = _unescape_mount_field(left[4])
        if resolved == mountpoint or resolved.startswith(mountpoint.rstrip("/") + "/"):
            matches.append((len(mountpoint), mountpoint, right[0]))

    if not matches:
        return None
    _, mountpoint, filesystem = max(matches, key=lambda item: item[0])
    return {
        "mountpoint": mountpoint,
        "filesystem": filesystem,
        "is_root_filesystem": mountpoint == "/",
    }


def _integrity_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    messages = [str(_row_value(row, 0) or "") for row in rows]
    ok = messages == ["ok"]
    return {
        "ok": ok,
        "issue_count": 0 if ok else len(messages),
        "issues": [] if ok else messages[:10],
        "issues_truncated": not ok and len(messages) > 10,
    }


def inspect_sqlite_path_diagnostics(
    *,
    connection: sqlite3.Connection,
    configured_db_path: str | Path,
    configured_data_dir: str | Path,
    data_dir_env_configured: bool,
) -> dict[str, Any]:
    """Inspect connection path, file metadata and SQLite integrity only.

    This function never opens another database connection and never returns
    application rows, environment values, credentials, or database payloads.
    """
    configured_path = Path(configured_db_path).expanduser().resolve(strict=False)
    data_dir = Path(configured_data_dir).expanduser().resolve(strict=False)

    database_rows = connection.execute("PRAGMA database_list").fetchall()
    main_path = ""
    for row in database_rows:
        if str(_row_value(row, 1)) == "main":
            main_path = str(_row_value(row, 2) or "")
            break

    actual_path = (
        Path(main_path).expanduser().resolve(strict=False)
        if main_path else None
    )
    actual_file = _file_metadata(actual_path) if actual_path else {
        "exists": False, "is_file": False, "size_bytes": None
    }

    sidecars: dict[str, Any] = {}
    if actual_path:
        for suffix in ("-wal", "-shm"):
            sidecars[suffix[1:]] = _file_metadata(Path(str(actual_path) + suffix))

    try:
        journal_mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(_row_value(journal_mode_row, 0) or "").lower()
    except sqlite3.Error:
        journal_mode = None

    parent = actual_path.parent if actual_path else configured_path.parent
    mount = _matching_mount(parent)

    return {
        "configured_data_dir": str(data_dir),
        "data_dir_env_configured": bool(data_dir_env_configured),
        "configured_db_path": str(configured_path),
        "opened_main_database_path": str(actual_path) if actual_path else None,
        "configured_path_matches_open_database": (
            actual_path == configured_path if actual_path else False
        ),
        "database_file": actual_file,
        "sidecar_files": sidecars,
        "journal_mode": journal_mode,
        "database_mount": mount,
        "path_under_var_data": (
            str(actual_path).startswith("/var/data/")
            if actual_path else False
        ),
        "integrity_check": _integrity_summary(connection),
        "read_only": True,
        "data_contents_exposed": False,
    }
