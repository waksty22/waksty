#!/usr/bin/env python3
"""End-to-end backup/restore probe against the explicitly isolated Chappie Turso DB.

The probe refuses a non-empty database before writing anything. It creates only
three uniquely named fixture tables, backs them up, removes those fixtures,
restores them, verifies values/FKs, then removes the fixtures again.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.backup_turso import create_backup_archive
from storage.hrana_backup import HranaTransactionConnection
from storage.hrana_http import HranaHttpClient, database_identity, open_guarded_restore_transaction
from storage.hrana_backup import HranaRestoreConnection
from storage.logical_backup import restore_encrypted_logical_backup, verify_encrypted_logical_backup

EXPECTED_HOST = "chappie-test-isolated-chapoue.aws-eu-west-1.turso.io"
TABLES = (
    "__chappie_probe_child",
    "__chappie_probe_parent",
    "__chappie_probe_blob",
)
FIXTURE_SQL = (
    "CREATE TABLE __chappie_probe_parent (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL)",
    "CREATE TABLE __chappie_probe_child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES __chappie_probe_parent(id), note TEXT NOT NULL)",
    "CREATE TABLE __chappie_probe_blob (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def open_client(url: str, token: str) -> HranaHttpClient:
    return HranaHttpClient(url, token, timeout=45.0)


def cleanup(url: str, token: str) -> None:
    client = open_client(url, token)
    tx = None
    try:
        tx = client.transaction()
        for table in TABLES:
            tx.execute_write(f'DROP TABLE IF EXISTS "{table}"')
        tx.commit()
        check = client.transaction()
        try:
            rows = check.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table', 'index', 'view', 'trigger')"
            ).rows
            require(not rows, "Cleanup verification found remaining user schema objects.")
            check.commit()
        except Exception:
            check.rollback()
            raise
    except Exception:
        if tx is not None:
            try:
                tx.rollback()
            except Exception:
                pass
        raise
    finally:
        client.close()


def main() -> int:
    url = os.environ.get("CHAPPIE_TEST_TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("CHAPPIE_TEST_TURSO_AUTH_TOKEN", "").strip()
    production_url = os.environ.get("CHAPPIE_PRODUCTION_TURSO_DATABASE_URL", "").strip()
    require(bool(url and token and production_url), "Required test/production identity settings are missing.")
    target = database_identity(url)
    production = database_identity(production_url)
    require(target == EXPECTED_HOST, "Refusing: test database hostname is not the approved isolated host.")
    require(target != production, "Refusing: isolated test target matches production hostname.")

    client = open_client(url, token)
    test_key = secrets.token_urlsafe(48)  # ephemeral key; never stored in repository/secrets
    fixtures_created = False
    try:
        # Strict preflight: never use a pre-existing database as a test fixture.
        preflight = client.transaction()
        try:
            existing = preflight.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table', 'index', 'view', 'trigger')"
            ).rows
            require(not existing, "Refusing to write: isolated test database is not empty.")
            preflight.commit()
        except Exception:
            preflight.rollback()
            raise

        # Mark cleanup as required before the first write: even an ambiguous
        # commit response must trigger best-effort removal of these exact names.
        fixtures_created = True
        seed = client.transaction()
        try:
            for statement in FIXTURE_SQL:
                seed.execute_write(statement)
            seed.execute_write(
                "INSERT INTO __chappie_probe_parent(label) VALUES (?)", ("parent-A",)
            )
            seed.execute_write(
                "INSERT INTO __chappie_probe_parent(label) VALUES (?)", ("parent-B",)
            )
            seed.execute_write(
                "INSERT INTO __chappie_probe_child(id, parent_id, note) VALUES (?, ?, ?)",
                (101, 1, "child-A"),
            )
            seed.execute_write(
                "INSERT INTO __chappie_probe_child(id, parent_id, note) VALUES (?, ?, ?)",
                (102, 2, "child-B"),
            )
            seed.execute_write(
                "INSERT INTO __chappie_probe_blob(id, payload) VALUES (?, ?)",
                (7, b"Chappie-Turso-probe\x00blob"),
            )
            seed.commit()
        except Exception:
            seed.rollback()
            raise

        with tempfile.TemporaryDirectory(prefix="chappie-turso-e2e-") as work:
            root = Path(work)
            archive_path = root / "chappie-isolated-probe.zip"
            backup_tx = client.transaction()
            try:
                report = create_backup_archive(
                    HranaTransactionConnection(backup_tx),
                    archive_path,
                    test_key,
                    manage_snapshot=False,
                )
                backup_tx.commit()
            except Exception:
                backup_tx.rollback()
                raise

            require(report.get("encrypted") is True, "Backup archive is not marked encrypted.")
            require(report.get("verified_after_packaging") is True, "Packaged backup verification failed.")
            require(report.get("table_count") == 3 and report.get("total_rows") == 5,
                    "Unexpected fixture backup counts.")

            with zipfile.ZipFile(archive_path, "r") as archive:
                expected_names = {"chappie-turso.json.enc", "chappie-turso.json.enc.sha256"}
                require(set(archive.namelist()) == expected_names, "Unexpected backup archive contents.")
                archive.extractall(root / "unpacked")
            encrypted_file = root / "unpacked" / "chappie-turso.json.enc"
            verification = verify_encrypted_logical_backup(encrypted_file, test_key)
            require(verification.get("valid") is True, "Encrypted backup failed independent verification.")

            # Empty only the known fixtures, then restore the authenticated artifact.
            empty_tx = client.transaction()
            try:
                for table in TABLES:
                    empty_tx.execute_write(f'DROP TABLE "{table}"')
                empty_tx.commit()
                fixtures_created = False
            except Exception:
                empty_tx.rollback()
                raise

            restore_client, restore_tx = open_guarded_restore_transaction(
                url,
                token,
                expected_target_identity=EXPECTED_HOST,
                production_identity=production,
            )
            try:
                restored = restore_encrypted_logical_backup(
                    HranaRestoreConnection(restore_tx),
                    encrypted_file,
                    test_key,
                    target_identity=target,
                    expected_target_identity=EXPECTED_HOST,
                    production_identity=production,
                )
                require(restored.get("restored") is True, "Restore adapter did not report success.")
                require(restored.get("table_count") == 3 and restored.get("total_rows") == 5,
                        "Restored table/row counts do not match.")

                check = HranaRestoreConnection(restore_tx)
                parent_rows = check.execute(
                    "SELECT id, label FROM __chappie_probe_parent ORDER BY id"
                ).fetchall()
                child_rows = check.execute(
                    "SELECT id, parent_id, note FROM __chappie_probe_child ORDER BY id"
                ).fetchall()
                blob_rows = check.execute(
                    "SELECT id, payload FROM __chappie_probe_blob"
                ).fetchall()
                require(parent_rows == [(1, "parent-A"), (2, "parent-B")],
                        "Parent rows differ after restore.")
                require(child_rows == [(101, 1, "child-A"), (102, 2, "child-B")],
                        "Child/FK rows differ after restore.")
                require(blob_rows == [(7, b"Chappie-Turso-probe\x00blob")],
                        "BLOB content differs after restore.")
                fk_rows = check.execute("PRAGMA foreign_key_check").fetchall()
                require(not fk_rows, "Foreign-key check failed after restore.")
                restore_tx.commit()
                fixtures_created = True
            except Exception:
                restore_tx.rollback()
                raise
            finally:
                restore_client.close()

            print(
                "E2E_SUCCESS "
                f"target={target} tables={restored['table_count']} rows={restored['total_rows']} "
                f"encrypted={report['encrypted']} archive_verified={report['verified_after_packaging']} "
                f"artifact_sha256={restored['artifact_sha256']} "
                "blob=ok foreign_keys=ok"
            )
        return 0
    finally:
        client.close()
        if fixtures_created:
            cleanup(url, token)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Do not print exception text: it may contain server-side details.
        print(f"E2E_FAILED {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
