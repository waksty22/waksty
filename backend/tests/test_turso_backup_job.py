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
                "chappie-turso.json.enc",
                "chappie-turso.json.enc.sha256",
            }
            extract_dir = tmp_path / "extracted"
            archive.extractall(extract_dir)

        assert verify_encrypted_logical_backup(
            extract_dir / "chappie-turso.json.enc", key
        )["valid"] is True
        assert verify_encrypted_logical_backup(
            extract_dir / "chappie-turso.json.enc",
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
