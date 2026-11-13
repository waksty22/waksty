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
        if not changed and 'FROM "child"' in sql:
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
    payload["summary"]["total_rows"] = 1000

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



def test_encrypted_restore_authenticates_artifact_before_writing(tmp_path):
    from storage.logical_backup import (
        export_encrypted_logical_backup,
        restore_encrypted_logical_backup,
    )

    source = _database()
    artifact = tmp_path / "verified.enc"
    password = "local-test-password-never-production"
    try:
        export_encrypted_logical_backup(source, artifact, password)
    finally:
        source.close()

    target = sqlite3.connect(":memory:")
    try:
        report = restore_encrypted_logical_backup(
            target, artifact, password,
            target_identity="isolated-restore-db",
            expected_target_identity="isolated-restore-db",
            production_identity="chappie-db",
        )
        assert report["artifact_authenticated"] is True
        assert report["logical_integrity_verified"] is True
        assert report["total_rows"] == 2
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        target.close()


def test_encrypted_restore_rejects_tampering_even_if_checksum_is_rewritten(tmp_path):
    from storage.logical_backup import (
        export_encrypted_logical_backup,
        restore_encrypted_logical_backup,
    )

    source = _database()
    artifact = tmp_path / "tampered.enc"
    password = "local-test-password-never-production"
    try:
        export_encrypted_logical_backup(source, artifact, password)
    finally:
        source.close()

    damaged = bytearray(artifact.read_bytes())
    damaged[-1] ^= 0x01
    artifact.write_bytes(damaged)
    digest = hashlib.sha256(damaged).hexdigest()
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(
        f"{digest}  {artifact.name}\\n", encoding="ascii"
    )

    target = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="Authentification AES-GCM"):
            restore_encrypted_logical_backup(
                target, artifact, password,
                target_identity="isolated-restore-db",
                expected_target_identity="isolated-restore-db",
                production_identity="chappie-db",
            )
        assert target.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall() == []
    finally:
        target.close()


def test_encrypted_restore_rejects_wrong_password_before_target_access(tmp_path):
    from storage.logical_backup import (
        export_encrypted_logical_backup,
        restore_encrypted_logical_backup,
    )

    source = _database()
    artifact = tmp_path / "wrong-key.enc"
    try:
        export_encrypted_logical_backup(
            source, artifact, "local-test-password-never-production"
        )
    finally:
        source.close()

    target = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="Authentification AES-GCM"):
            restore_encrypted_logical_backup(
                target, artifact, "another-local-test-password",
                target_identity="isolated-restore-db",
                expected_target_identity="isolated-restore-db",
                production_identity="chappie-db",
            )
        assert target.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall() == []
    finally:
        target.close()


def test_encrypted_restore_through_hrana_adapter_with_foreign_keys_enabled(tmp_path):
    from storage.hrana_backup import HranaRestoreConnection
    from storage.logical_backup import (
        export_encrypted_logical_backup,
        restore_encrypted_logical_backup,
    )

    class LocalHranaTransaction:
        """Execute Hrana-like bound statements against an isolated SQLite target."""
        def __init__(self):
            self.db = sqlite3.connect(":memory:")
            self.db.execute("PRAGMA foreign_keys = ON")
            # HranaRestoreConnection wraps an already-open remote transaction.
            self.db.execute("BEGIN")
            self.committed = False
            self.rolled_back = False

        def execute_write(self, sql, args=()):
            cursor = self.db.execute(sql, tuple(args))
            return type("Result", (), {
                "columns": tuple(item[0] for item in (cursor.description or ())),
                "rows": cursor.fetchall() if cursor.description else [],
            })()

        def commit(self):
            self.db.commit()
            self.committed = True

        def rollback(self):
            self.db.rollback()
            self.rolled_back = True

    source = _database()
    artifact = tmp_path / "hrana-restore.enc"
    password = "local-test-password-never-production"
    try:
        export_encrypted_logical_backup(source, artifact, password)
    finally:
        source.close()

    transaction = LocalHranaTransaction()
    adapter = HranaRestoreConnection(transaction)
    try:
        report = restore_encrypted_logical_backup(
            adapter,
            artifact,
            password,
            target_identity="isolated-test-db.turso.io",
            expected_target_identity="isolated-test-db.turso.io",
            production_identity="chappie-db.turso.io",
        )
        assert report["restored"] is True
        assert report["total_rows"] == 2
        assert transaction.db.execute(
            "SELECT payload FROM parent WHERE id=1"
        ).fetchone()[0] == bytes([0, 1, 255])
        assert transaction.db.execute(
            "SELECT note FROM child WHERE id=2"
        ).fetchone()[0] == "existing Turso row"
        assert transaction.db.execute("PRAGMA foreign_key_check").fetchall() == []
        adapter.commit()
        assert transaction.committed is True
    finally:
        if adapter.in_transaction:
            adapter.rollback()
        transaction.db.close()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["objects"].append("not-an-object"),
        lambda payload: payload["tables"][0].update(name=[]),
        lambda payload: payload["summary"]["row_counts"].update(child="1"),
        lambda payload: payload["summary"].update(total_rows=True),
    ],
)
def test_logical_restore_rejects_malformed_payload_before_target_changes(tmp_path, mutate):
    from storage.logical_backup import restore_logical_backup_payload

    source = _database()
    backup_path = tmp_path / "malformed-source.json"
    try:
        export_logical_backup(source, backup_path)
    finally:
        source.close()
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    mutate(payload)

    target = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError):
            restore_logical_backup_payload(
                target,
                payload,
                target_identity="isolated-restore-db",
                expected_target_identity="isolated-restore-db",
                production_identity="chappie-db",
            )
        assert target.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall() == []
    finally:
        target.close()


def test_logical_backup_preserves_autoincrement_sequence_after_deleted_rows(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL
        );
        INSERT INTO events(description) VALUES ('one'), ('two'), ('three'), ('four'), ('five');
        DELETE FROM events;
    """)
    artifact = tmp_path / "autoincrement.json"
    try:
        export_logical_backup(source, artifact)
    finally:
        source.close()

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["sequences"] == [{"table": "events", "seq": 5}]
    target = sqlite3.connect(":memory:")
    try:
        restore_logical_backup_payload(
            target, payload,
            target_identity="isolated-sequence-test",
            expected_target_identity="isolated-sequence-test",
            production_identity="chappie-db",
        )
        cursor = target.execute(
            "INSERT INTO events(description) VALUES ('after restore')"
        )
        assert cursor.lastrowid == 6
    finally:
        target.close()


def test_logical_backup_excludes_generated_columns_from_restore_inserts(tmp_path):
    from storage.logical_backup import restore_logical_backup_payload

    source = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE measurements(
            value INTEGER NOT NULL,
            doubled INTEGER GENERATED ALWAYS AS (value * 2) STORED
        );
        INSERT INTO measurements(value) VALUES (7), (11);
    """)
    artifact = tmp_path / "generated-columns.json"
    try:
        result = export_logical_backup(source, artifact)
        assert result["verified"] is True
    finally:
        source.close()

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["tables"][0]["columns"] == ["value"]
    target = sqlite3.connect(":memory:")
    try:
        restore_logical_backup_payload(
            target, payload,
            target_identity="isolated-generated-test",
            expected_target_identity="isolated-generated-test",
            production_identity="chappie-db",
        )
        assert target.execute(
            "SELECT value, doubled FROM measurements ORDER BY value"
        ).fetchall() == [(7, 14), (11, 22)]
    finally:
        target.close()


def test_logical_backup_does_not_assume_sqlite_sequence_from_sql_comment(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute(
        "CREATE TABLE notes(id INTEGER PRIMARY KEY, note TEXT) "
        "/* AUTOINCREMENT appears here only as a comment */"
    )
    source.execute("INSERT INTO notes(note) VALUES ('safe')")
    artifact = tmp_path / "comment-autoincrement.json"
    try:
        report = export_logical_backup(source, artifact)
        assert report["verified"] is True
    finally:
        source.close()

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["sequences"] == []



def test_logical_export_cleans_partial_artifacts_when_verification_fails(tmp_path, monkeypatch):
    import storage.logical_backup as backup

    db = _database()
    target = tmp_path / "unverified.json"
    monkeypatch.setattr(
        backup, "verify_logical_backup",
        lambda path: {"valid": False, "reason": "forced_test_failure"},
    )
    try:
        with pytest.raises(ValueError, match="local restore verification"):
            backup.export_logical_backup(db, target)
        assert not target.exists()
        assert not target.with_suffix(target.suffix + ".sha256").exists()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        db.close()


def test_logical_export_refuses_existing_checksum_without_overwriting(tmp_path):
    db = _database()
    target = tmp_path / "backup.json"
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text("preserve this checksum", encoding="ascii")
    try:
        with pytest.raises(FileExistsError, match="checksum"):
            export_logical_backup(db, target)
        assert not target.exists()
        assert checksum.read_text(encoding="ascii") == "preserve this checksum"
    finally:
        db.close()



def test_logical_export_never_overwrites_destination_created_concurrently(tmp_path, monkeypatch):
    import storage.logical_backup as backup

    db = _database()
    target = tmp_path / "racing.json"
    real_link = backup.os.link

    def competing_link(source, destination):
        Path(destination).write_text("owned by competing exporter", encoding="utf-8")
        return real_link(source, destination)

    from pathlib import Path
    monkeypatch.setattr(backup.os, "link", competing_link)
    try:
        with pytest.raises(FileExistsError):
            backup.export_logical_backup(db, target)
        assert target.read_text(encoding="utf-8") == "owned by competing exporter"
        assert not target.with_suffix(target.suffix + ".sha256").exists()
    finally:
        db.close()


def test_logical_export_preserves_checksum_created_concurrently(tmp_path, monkeypatch):
    import storage.logical_backup as backup
    from pathlib import Path

    db = _database()
    target = tmp_path / "racing-checksum.json"
    checksum = target.with_suffix(target.suffix + ".sha256")
    real_link = backup.os.link
    calls = 0

    def competing_checksum_link(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(destination).write_text("owned by competing exporter", encoding="ascii")
        return real_link(source, destination)

    monkeypatch.setattr(backup.os, "link", competing_checksum_link)
    try:
        with pytest.raises(FileExistsError):
            backup.export_logical_backup(db, target)
        assert not target.exists()
        assert checksum.read_text(encoding="ascii") == "owned by competing exporter"
    finally:
        db.close()


def test_encrypted_export_refuses_existing_checksum_without_deleting_it(tmp_path):
    db = _database()
    target = tmp_path / "encrypted-existing-checksum.enc"
    checksum = target.with_suffix(target.suffix + ".sha256")
    checksum.write_text("preserve existing checksum", encoding="ascii")
    try:
        with pytest.raises(FileExistsError, match="checksum"):
            export_encrypted_logical_backup(db, target, "test-only-password-123")
        assert not target.exists()
        assert checksum.read_text(encoding="ascii") == "preserve existing checksum"
    finally:
        db.close()


def test_encrypted_export_never_overwrites_concurrent_destination(tmp_path, monkeypatch):
    import storage.logical_backup as backup
    from pathlib import Path

    db = _database()
    target = tmp_path / "encrypted-racing.enc"
    real_link = backup.os.link

    def competing_link(source, destination):
        if Path(destination) == target:
            target.write_bytes(b"owned by competing exporter")
        return real_link(source, destination)

    monkeypatch.setattr(backup.os, "link", competing_link)
    try:
        with pytest.raises(FileExistsError):
            backup.export_encrypted_logical_backup(db, target, "test-only-password-123")
        assert target.read_bytes() == b"owned by competing exporter"
        assert not target.with_suffix(target.suffix + ".sha256").exists()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        db.close()
