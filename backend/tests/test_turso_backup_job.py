import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backup_turso import create_backup_archive
from storage.logical_backup import verify_encrypted_logical_backup


def _database():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL
        );
        INSERT INTO memories VALUES (1, 'creator', 'test-only memory');
        """
    )
    return db


def test_backup_job_creates_encrypted_archive_and_verifies_packaged_file(tmp_path):
    db = _database()
    output = tmp_path / "chappie-backup.zip"
    key = "test-only-backup-key-not-production"
    try:
        result = create_backup_archive(db, output, key)
        assert result["encrypted"] is True
        assert result["verified_after_packaging"] is True
        assert result["table_count"] == 1
        assert result["total_rows"] == 1
        assert output.exists()

        with zipfile.ZipFile(output) as archive:
            assert set(archive.namelist()) == {
                "chappie-turso-backup.json.enc",
                "chappie-turso-backup.json.enc.sha256",
            }
            extract_dir = tmp_path / "extracted"
            archive.extractall(extract_dir)

        assert verify_encrypted_logical_backup(
            extract_dir / "chappie-turso-backup.json.enc", key
        )["valid"] is True
        assert verify_encrypted_logical_backup(
            extract_dir / "chappie-turso-backup.json.enc",
            "incorrect-test-key",
        )["valid"] is False
    finally:
        db.close()


def test_backup_job_refuses_to_overwrite_existing_archive(tmp_path):
    db = _database()
    output = tmp_path / "existing.zip"
    output.write_bytes(b"preserve this file")
    try:
        with pytest.raises(FileExistsError):
            create_backup_archive(
                db, output, "test-only-backup-key-not-production"
            )
        assert output.read_bytes() == b"preserve this file"
    finally:
        db.close()


def test_backup_job_supports_serialized_hrana_select_transaction(tmp_path):
    from storage.hrana_backup import HranaTransactionConnection

    db = _database()

    class FakeHranaResult:
        def __init__(self, cursor):
            self.columns = [column[0] for column in cursor.description or []]
            self.rows = cursor.fetchall()

    class FakeHranaTransaction:
        def execute(self, sql):
            assert sql.lstrip().upper().startswith("SELECT")
            assert ";" not in sql
            return FakeHranaResult(db.execute(sql))

    output = tmp_path / "hrana-backup.zip"
    try:
        result = create_backup_archive(
            HranaTransactionConnection(FakeHranaTransaction()),
            output,
            "test-only-backup-key-not-production",
            manage_snapshot=False,
        )
        assert result["verified_after_packaging"] is True
        assert result["total_rows"] == 1
    finally:
        db.close()


def test_backup_job_cleans_partial_archive_when_packaged_verification_fails(tmp_path, monkeypatch):
    import backup_turso

    db = _database()
    output = tmp_path / "unverified.zip"
    monkeypatch.setattr(
        backup_turso,
        "verify_encrypted_logical_backup",
        lambda path, key: {"valid": False, "reason": "forced_test_failure"},
    )
    try:
        with pytest.raises(ValueError, match="Packaged backup verification failed"):
            create_backup_archive(db, output, "test-only-backup-key-not-production")
        assert not output.exists()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        db.close()


def test_backup_job_never_overwrites_archive_created_concurrently(tmp_path, monkeypatch):
    import backup_turso

    db = _database()
    output = tmp_path / "racing.zip"
    real_link = backup_turso.os.link

    def competing_link(source, destination):
        if Path(destination) == output:
            Path(destination).write_bytes(b"owned by competing exporter")
        return real_link(source, destination)

    monkeypatch.setattr(backup_turso.os, "link", competing_link)
    try:
        with pytest.raises(FileExistsError):
            create_backup_archive(db, output, "test-only-backup-key-not-production")
        assert output.read_bytes() == b"owned by competing exporter"
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        db.close()


def test_backup_job_preserves_verification_error_when_temp_cleanup_fails(
    tmp_path, monkeypatch
):
    import backup_turso

    db = _database()
    output = tmp_path / "cleanup-failure.zip"
    real_unlink = Path.unlink
    attempted = []

    def fail_temp_cleanup(path, *args, **kwargs):
        if path.name.startswith(output.name + ".") and path.suffix == ".tmp":
            attempted.append(path)
            raise OSError("simulated temporary archive cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temp_cleanup)
    monkeypatch.setattr(
        backup_turso,
        "verify_encrypted_logical_backup",
        lambda path, key: {"valid": False, "reason": "forced_test_failure"},
    )
    try:
        with pytest.raises(
            ValueError, match="Packaged backup verification failed"
        ):
            create_backup_archive(
                db, output, "test-only-backup-key-not-production"
            )
        assert len(attempted) == 1
        assert not output.exists()
        assert attempted[0].exists()
    finally:
        db.close()



def test_turso_backup_http_endpoint_returns_verified_archive(monkeypatch):
    import asyncio
    import hashlib
    import io

    import server
    import storage.hrana_http as hrana_http

    database = _database()
    lifecycle = {"committed": False, "closed": False}

    class FakeHranaResult:
        def __init__(self, cursor):
            self.columns = [column[0] for column in cursor.description or []]
            self.rows = cursor.fetchall()

    class FakeTransaction:
        def execute(self, sql):
            assert sql.lstrip().upper().startswith("SELECT")
            assert ";" not in sql
            return FakeHranaResult(database.execute(sql))

        def commit(self):
            database.commit()
            lifecycle["committed"] = True

        def rollback(self):
            database.rollback()

    class FakeClient:
        def __init__(self, database_url, auth_token):
            assert database_url == "libsql://isolated-test.invalid"
            assert auth_token == "isolated-test-token"

        def transaction(self):
            return FakeTransaction()

        def close(self):
            lifecycle["closed"] = True

    monkeypatch.setattr(hrana_http, "HranaHttpClient", FakeClient)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://isolated-test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "isolated-test-token")
    monkeypatch.setenv(
        "BACKUP_ENCRYPTION_KEY", "test-only-backup-key-not-production"
    )

    try:
        response = asyncio.run(server.api_turso_backup(auth="creator"))
        assert response.status_code == 200
        assert lifecycle == {"committed": True, "closed": True}

        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            expected = {
                "chappie-turso-backup.json.enc",
                "chappie-turso-backup.json.enc.sha256",
            }
            assert len(archive.namelist()) == len(expected)
            assert set(archive.namelist()) == expected
            encrypted = archive.read("chappie-turso-backup.json.enc")
            sidecar = archive.read(
                "chappie-turso-backup.json.enc.sha256"
            ).decode("ascii").split()[0]

        digest = hashlib.sha256(encrypted).hexdigest()
        assert digest == sidecar
        assert response.headers["x-backup-sha256"] == digest
        assert response.headers["x-backup-verified"] == "true"
        assert response.headers["x-backup-encrypted"] == "AES-256-GCM"
        assert response.headers["x-backup-format"] == (
            "ZIP: encrypted backup + SHA-256 sidecar"
        )
        assert response.headers["x-backup-table-count"] == "1"
        assert response.headers["x-backup-row-count"] == "1"

        # Independently decrypt and validate the exact ciphertext returned by HTTP.
        import tempfile

        from storage.logical_backup import verify_encrypted_logical_backup

        with tempfile.TemporaryDirectory() as directory:
            encrypted_path = Path(directory) / "chappie-turso-backup.json.enc"
            checksum_path = encrypted_path.with_suffix(
                encrypted_path.suffix + ".sha256"
            )
            encrypted_path.write_bytes(encrypted)
            checksum_path.write_text(digest + "  " + encrypted_path.name + "\\n")
            verification = verify_encrypted_logical_backup(
                encrypted_path, "test-only-backup-key-not-production"
            )
        assert verification["valid"] is True
    finally:
        database.close()
