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

def test_backup_job_verification_never_calls_extractall(tmp_path, monkeypatch):
    db = _database()
    output = tmp_path / "no-extractall.zip"

    def forbidden_extractall(*args, **kwargs):
        raise AssertionError("extractall must not be used for backup verification")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden_extractall)
    try:
        result = create_backup_archive(
            db, output, "test-only-backup-key-not-production"
        )
        assert result["verified_after_packaging"] is True
        assert output.exists()
    finally:
        db.close()


def test_backup_job_rejects_duplicate_archive_members(tmp_path, monkeypatch):
    import backup_turso

    db = _database()
    output = tmp_path / "duplicate-members.zip"
    original_namelist = zipfile.ZipFile.namelist

    def duplicate_member(archive):
        names = original_namelist(archive)
        return names + names[:1]

    monkeypatch.setattr(zipfile.ZipFile, "namelist", duplicate_member)
    try:
        with pytest.raises(ValueError, match="duplicate"):
            create_backup_archive(
                db, output, "test-only-backup-key-not-production"
            )
        assert not output.exists()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        db.close()

