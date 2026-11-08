import hashlib
import json
import sqlite3

import pytest

from storage.logical_backup import export_logical_backup, verify_logical_backup


def _database():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE parent(id INTEGER PRIMARY KEY, payload BLOB);
        CREATE TABLE child(
            id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL REFERENCES parent(id),
            note TEXT
        );
        CREATE INDEX idx_child_parent ON child(parent_id);
        INSERT INTO parent VALUES (1, X'0001FF');
        INSERT INTO child VALUES (2, 1, 'existing Turso row');
    """)
    return db


def test_export_is_portable_checksum_verified_and_restorable(tmp_path):
    db = _database()
    target = tmp_path / "turso-backup.json"
    try:
        result = export_logical_backup(db, target)
        assert result["verified"] is True
        assert result["table_count"] == 2
        assert result["total_rows"] == 2
        assert len(result["sha256"]) == 64
        assert verify_logical_backup(target)["valid"] is True
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["summary"]["row_counts"] == {"child": 1, "parent": 1}
        assert payload["tables"][1]["rows"][0][1] == {
            "__type__": "blob",
            "base64": "AAH/"
        }
    finally:
        db.close()


def test_export_refuses_overwrite(tmp_path):
    db = _database()
    target = tmp_path / "backup.json"
    target.write_text("do not overwrite", encoding="utf-8")
    try:
        with pytest.raises(FileExistsError):
            export_logical_backup(db, target)
        assert target.read_text(encoding="utf-8") == "do not overwrite"
    finally:
        db.close()


def test_verifier_detects_tampering(tmp_path):
    db = _database()
    target = tmp_path / "backup.json"
    try:
        export_logical_backup(db, target)
        target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
        result = verify_logical_backup(target)
        assert result["valid"] is False
        assert result["reason"] == "checksum_mismatch"
    finally:
        db.close()


def test_encrypted_export_never_leaves_plaintext_artifact(tmp_path):
    from storage.logical_backup import (
        export_encrypted_logical_backup,
        verify_encrypted_logical_backup,
    )
    db = _database()
    target = tmp_path / "private-turso-backup.enc"
    password = "local-test-password-never-production"
    try:
        result = export_encrypted_logical_backup(db, target, password)
        assert result["encrypted"] is True
        assert result["verified"] is True
        assert target.read_bytes().startswith(b"CHAPPIE-LOGICAL-V1")
        assert not (tmp_path / "snapshot.json").exists()
        assert verify_encrypted_logical_backup(target, password)["valid"] is True
        assert verify_encrypted_logical_backup(target, "wrong-password")["valid"] is False
    finally:
        db.close()
