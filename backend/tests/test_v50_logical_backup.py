from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
import sys

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from storage.logical_backup import (
    export_encrypted_logical_backup,
    export_logical_backup,
    verify_encrypted_logical_backup,
    verify_logical_backup,
)


def _sample_database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL, photo BLOB)"
    )
    db.execute("CREATE INDEX people_name_idx ON people(name)")
    db.execute("CREATE VIEW named_people AS SELECT id, name FROM people")
    db.execute(
        "CREATE TABLE audit (id INTEGER PRIMARY KEY, person_id INTEGER, "
        "FOREIGN KEY(person_id) REFERENCES people(id))"
    )
    db.execute(
        "CREATE TRIGGER people_insert_audit AFTER INSERT ON people "
        "BEGIN INSERT INTO audit(person_id) VALUES (NEW.id); END"
    )
    db.execute(
        "INSERT INTO people(name, photo) VALUES (?, ?)",
        ("Chappie", sqlite3.Binary(b"\\x00\\x01photo")),
    )
    db.commit()
    return db


def test_logical_backup_exports_schema_rows_and_blobs_and_verifies(tmp_path):
    db = _sample_database()
    destination = tmp_path / "snapshot.json"
    try:
        result = export_logical_backup(db, destination)
        verification = verify_logical_backup(destination)

        assert result["verified"] is True
        assert result["table_count"] == 2
        assert result["total_rows"] == 2
        assert verification["valid"] is True
        assert verification["foreign_key_violations"] == 0
        assert verification["row_counts_match"] is True
        assert (tmp_path / "snapshot.json.sha256").is_file()
    finally:
        db.close()


def test_logical_backup_detects_artifact_tampering(tmp_path):
    db = _sample_database()
    destination = tmp_path / "snapshot.json"
    try:
        export_logical_backup(db, destination)
        destination.write_bytes(destination.read_bytes() + b" ")
        verification = verify_logical_backup(destination)
        assert verification["valid"] is False
        assert verification["reason"] == "checksum_mismatch"
    finally:
        db.close()


def test_logical_backup_refuses_to_overwrite_existing_artifact(tmp_path):
    db = _sample_database()
    destination = tmp_path / "snapshot.json"
    destination.write_text("keep this file", encoding="utf-8")
    try:
        with pytest.raises(FileExistsError, match="Refusing to overwrite"):
            export_logical_backup(db, destination)
        assert destination.read_text(encoding="utf-8") == "keep this file"
    finally:
        db.close()


def test_encrypted_logical_backup_verifies_exact_ciphertext_and_restore(tmp_path):
    db = _sample_database()
    destination = tmp_path / "snapshot.json.enc"
    try:
        result = export_encrypted_logical_backup(
            db, destination, "test-encryption-key-long-enough"
        )
        verification = verify_encrypted_logical_backup(
            destination, "test-encryption-key-long-enough"
        )

        assert result["verified"] is True
        assert result["encrypted"] is True
        assert result["verification"] == {
            "checksum": True,
            "decryption": True,
            "restore_integrity": True,
        }
        assert verification["valid"] is True
        assert verification["encrypted"] is True
        assert destination.read_bytes().startswith(b"CHAPPIE-LOGICAL-V1")
        assert not (tmp_path / "snapshot.json").exists()
    finally:
        db.close()



def test_logical_backup_refuses_preexisting_checksum_without_creating_data(tmp_path):
    db = _sample_database()
    destination = tmp_path / "snapshot.json"
    checksum = tmp_path / "snapshot.json.sha256"
    checksum.write_text("preserve this checksum", encoding="ascii")
    try:
        with pytest.raises(FileExistsError, match="Refusing to overwrite"):
            export_logical_backup(db, destination)
        assert not destination.exists()
        assert checksum.read_text(encoding="ascii") == "preserve this checksum"
    finally:
        db.close()


def test_logical_backup_removes_partial_artifacts_when_restore_verification_fails(
    tmp_path, monkeypatch
):
    import storage.logical_backup as logical_backup

    db = _sample_database()
    destination = tmp_path / "snapshot.json"
    monkeypatch.setattr(
        logical_backup,
        "verify_logical_backup",
        lambda path: {"valid": False, "reason": "forced_test_failure"},
    )
    try:
        with pytest.raises(ValueError, match="local restore verification"):
            logical_backup.export_logical_backup(db, destination)
        assert not destination.exists()
        assert not (tmp_path / "snapshot.json.sha256").exists()
        assert list(tmp_path.iterdir()) == []
    finally:
        db.close()
