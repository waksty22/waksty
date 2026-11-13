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
        assert result["verification"] == {
            "checksum": True,
            "decryption": True,
            "restore_integrity": True,
        }
        assert target.read_bytes().startswith(b"CHAPPIE-LOGICAL-V1")
        assert not (tmp_path / "snapshot.json").exists()
        assert verify_encrypted_logical_backup(target, password)["valid"] is True
        assert verify_encrypted_logical_backup(target, "wrong-password")["valid"] is False
    finally:
        db.close()



def test_logical_export_uses_one_consistent_wal_snapshot(tmp_path, monkeypatch):
    import storage.logical_backup as backup

    db_path = tmp_path / "snapshot.sqlite3"
    setup = sqlite3.connect(db_path)
    setup.execute("PRAGMA journal_mode=WAL")
    setup.executescript("""
        CREATE TABLE child(id INTEGER PRIMARY KEY, note TEXT);
        CREATE TABLE parent(id INTEGER PRIMARY KEY, note TEXT);
        INSERT INTO child VALUES (1, 'child-before');
        INSERT INTO parent VALUES (1, 'parent-before');
    """)
    setup.close()

    reader = sqlite3.connect(db_path, timeout=2)
    writer = sqlite3.connect(db_path, timeout=2)
    original_query_rows = backup._query_rows
    changed = False

    def concurrent_writer(connection, sql):
        nonlocal changed
        result = original_query_rows(connection, sql)
        if not changed and 'SELECT * FROM "child"' in sql:
            writer.execute("INSERT INTO parent VALUES (2, 'committed-during-export')")
            writer.commit()
            changed = True
        return result

    monkeypatch.setattr(backup, "_query_rows", concurrent_writer)
    target = tmp_path / "consistent.json"
    try:
        result = backup.export_logical_backup(reader, target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        counts = payload["summary"]["row_counts"]
        assert changed is True
        assert result["verified"] is True
        # The writer committed while the export was running, but the export
        # must contain the same pre-commit snapshot for every table.
        assert counts == {"child": 1, "parent": 1}
        assert writer.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 2
    finally:
        reader.close()
        writer.close()


def test_encrypted_export_refuses_to_report_unverified_ciphertext(tmp_path, monkeypatch):
    import storage.logical_backup as backup

    db = _database()
    target = tmp_path / "must-not-be-trusted.enc"
    password = "local-test-password-never-production"
    monkeypatch.setattr(
        backup,
        "verify_encrypted_logical_backup",
        lambda path, key: {"valid": False, "reason": "forced_test_failure"},
    )
    try:
        with pytest.raises(ValueError, match="final on-disk verification"):
            backup.export_encrypted_logical_backup(db, target, password)
        assert not target.exists()
        assert not target.with_suffix(target.suffix + ".sha256").exists()
    finally:
        db.close()


def test_guarded_logical_restore_populates_only_explicit_empty_target(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = _database()
    backup_path = tmp_path / "known-good.json"
    try:
        export_logical_backup(source, backup_path)
    finally:
        source.close()
    payload = json.loads(backup_path.read_text(encoding="utf-8"))

    target = sqlite3.connect(":memory:")
    try:
        report = restore_logical_backup_payload(
            target, payload,
            target_identity="chappie-restore-test",
            expected_target_identity="chappie-restore-test",
            production_identity="chappie-db",
        )
        assert report["restored"] is True
        assert report["table_count"] == 2
        assert report["total_rows"] == 2
        assert target.execute("SELECT payload FROM parent WHERE id=1").fetchone()[0] == bytes([0, 1, 255])
        assert target.execute("SELECT note FROM child WHERE id=2").fetchone()[0] == "existing Turso row"
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        target.close()


def test_guarded_logical_restore_refuses_production_or_wrong_identity(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = _database()
    backup_path = tmp_path / "backup.json"
    try:
        export_logical_backup(source, backup_path)
    finally:
        source.close()
    payload = json.loads(backup_path.read_text(encoding="utf-8"))

    for target_id, expected_id in [
        ("chappie-db", "chappie-db"),
        ("other-test-db", "chappie-restore-test"),
    ]:
        target = sqlite3.connect(":memory:")
        try:
            with pytest.raises(PermissionError):
                restore_logical_backup_payload(
                    target, payload,
                    target_identity=target_id,
                    expected_target_identity=expected_id,
                    production_identity="chappie-db",
                )
            assert target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        finally:
            target.close()


def test_guarded_logical_restore_refuses_nonempty_target_without_changes(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = _database()
    backup_path = tmp_path / "backup.json"
    try:
        export_logical_backup(source, backup_path)
    finally:
        source.close()
    payload = json.loads(backup_path.read_text(encoding="utf-8"))

    target = sqlite3.connect(":memory:")
    try:
        target.execute("CREATE TABLE keep_me(value TEXT)")
        target.execute("INSERT INTO keep_me VALUES ('untouched')")
        target.commit()
        with pytest.raises(PermissionError, match="pas vide"):
            restore_logical_backup_payload(
                target, payload,
                target_identity="chappie-restore-test",
                expected_target_identity="chappie-restore-test",
                production_identity="chappie-db",
            )
        assert target.execute("SELECT value FROM keep_me").fetchone()[0] == "untouched"
    finally:
        target.close()


def test_guarded_logical_restore_rolls_back_on_invalid_row_count(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = _database()
    backup_path = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "backup.json"
    try:
        export_logical_backup(source, backup_path)
    finally:
        source.close()
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    backup_path.unlink()
    backup_path.with_suffix(".json.sha256").unlink(missing_ok=True)
    backup_path.parent.rmdir()
    payload["summary"]["row_counts"]["child"] = 999

    target = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="nombres de lignes"):
            restore_logical_backup_payload(
                target, payload,
                target_identity="chappie-restore-test",
                expected_target_identity="chappie-restore-test",
                production_identity="chappie-db",
            )
        assert target.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        target.close()
