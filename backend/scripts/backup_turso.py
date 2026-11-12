#!/usr/bin/env python3
"""Create an encrypted, verified logical backup of the active Turso database."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from storage.logical_backup import (  # noqa: E402
    export_encrypted_logical_backup,
    verify_encrypted_logical_backup,
)


def create_backup_archive(
    connection: Any,
    output_path: str | Path,
    encryption_key: str,
) -> dict[str, Any]:
    """Create and re-verify a ZIP containing ciphertext and its SHA-256 sidecar."""
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite backup archive: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="chappie-turso-job-") as work:
        root = Path(work)
        encrypted_path = root / "chappie-turso.json.enc"
        report = export_encrypted_logical_backup(
            connection, encrypted_path, encryption_key
        )
        checksum_path = encrypted_path.with_suffix(
            encrypted_path.suffix + ".sha256"
        )

        with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_STORED) as archive:
            archive.write(encrypted_path, arcname=encrypted_path.name)
            archive.write(checksum_path, arcname=checksum_path.name)

        # Verify the exact artifact after packaging, not only the source file.
        verify_dir = root / "archive-verification"
        verify_dir.mkdir()
        with zipfile.ZipFile(output, mode="r") as archive:
            expected = {
                encrypted_path.name,
                checksum_path.name,
            }
            if set(archive.namelist()) != expected:
                raise ValueError("Backup archive contains unexpected files.")
            archive.extractall(verify_dir)

        packaged_backup = verify_dir / encrypted_path.name
        verification = verify_encrypted_logical_backup(
            packaged_backup, encryption_key
        )
        if not verification.get("valid"):
            raise ValueError(
                "Packaged backup verification failed: "
                + str(verification.get("reason", "unknown"))
            )

    return {
        "archive": str(output),
        "sha256": report["sha256"],
        "size_bytes": output.stat().st_size,
        "table_count": report["table_count"],
        "total_rows": report["total_rows"],
        "encrypted": True,
        "verified_after_packaging": True,
        "encryption": report["encryption"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="backup-output")
    args = parser.parse_args()

    database_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    encryption_key = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    if not database_url or not auth_token or len(encryption_key) < 12:
        print(
            "Backup refused: required Turso or encryption settings are missing.",
            file=sys.stderr,
        )
        return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output_dir) / f"chappie-turso-{timestamp}.zip"
    connection = None
    try:
        import libsql

        connection = libsql.connect(
            database=database_url,
            auth_token=auth_token,
        )
        connection.execute("SELECT 1").fetchone()
        result = create_backup_archive(connection, output, encryption_key)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Never include exception text: database clients can echo connection data.
        print(
            f"Backup failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
