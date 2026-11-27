#!/usr/bin/env python3
"""Restore the actual encrypted daily backup into disposable in-memory SQLite.

The production database is never contacted. The artifact is downloaded by the
GitHub workflow, authenticated/decrypted, and reconstructed only in a local
SQLite :memory: database on the ephemeral runner.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.backup_turso import (  # noqa: E402
    BACKUP_CHECKSUM_NAME,
    BACKUP_CIPHERTEXT_NAME,
    _extract_expected_archive_members,
)
from storage.logical_backup import (  # noqa: E402
    restore_encrypted_logical_backup,
    verify_encrypted_logical_backup,
)


def restore_daily_artifact(artifact_dir: str | Path, encryption_key: str) -> dict[str, Any]:
    """Authenticate and restore exactly one daily archive into disposable SQLite."""
    root = Path(artifact_dir).expanduser().resolve()
    archives = sorted(path for path in root.glob("*.zip") if path.is_file())
    if len(archives) != 1:
        raise ValueError("Expected exactly one downloaded daily backup archive.")

    with tempfile.TemporaryDirectory(prefix="chappie-daily-recovery-") as work:
        workdir = Path(work)
        encrypted_dir = workdir / "encrypted"
        encrypted_dir.mkdir()
        with zipfile.ZipFile(archives[0], "r") as archive:
            _extract_expected_archive_members(
                archive,
                encrypted_dir,
                {BACKUP_CIPHERTEXT_NAME, BACKUP_CHECKSUM_NAME},
            )

        encrypted_path = encrypted_dir / BACKUP_CIPHERTEXT_NAME
        verification = verify_encrypted_logical_backup(encrypted_path, encryption_key)
        if verification.get("valid") is not True or verification.get("encrypted") is not True:
            raise ValueError("Daily encrypted backup authentication or integrity check failed.")

        # In-memory SQLite is the only restore destination. No production or
        # secondary Turso credentials are loaded by this script.
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            restored = restore_encrypted_logical_backup(
                connection,
                encrypted_path,
                encryption_key,
                target_identity="isolated-local-sqlite-memory",
                expected_target_identity="isolated-local-sqlite-memory",
                production_identity="production-turso",
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            object_count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table', 'index', 'view', 'trigger')"
            ).fetchone()[0]
            if integrity != "ok" or foreign_key_violations:
                raise ValueError("Restored database failed SQLite integrity checks.")
            if restored.get("restored") is not True or object_count < 1:
                raise ValueError("Daily backup restore produced no verifiable schema.")
            return {
                "success": True,
                "artifact_sha256": restored["artifact_sha256"],
                "table_count": restored["table_count"],
                "total_rows": restored["total_rows"],
                "schema_object_count": int(object_count),
                "integrity_check": integrity,
                "foreign_key_violations": len(foreign_key_violations),
                "destination": "disposable in-memory SQLite",
                "production_database_contacted": False,
            }
        finally:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    key = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    if len(key) < 12:
        print("Recovery drill refused: encryption key is missing or invalid.", file=sys.stderr)
        return 2
    try:
        report = restore_daily_artifact(args.artifact_dir, key)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Never print exception text: it may contain remote or payload details.
        print(f"Recovery drill failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
