from __future__ import annotations

import sqlite3

from scripts.backup_turso import create_backup_archive
from scripts.test_daily_encrypted_backup_recovery import restore_daily_artifact


def test_actual_encrypted_daily_archive_restores_into_disposable_sqlite(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute("PRAGMA foreign_keys = ON")
    source.execute(
        "CREATE TABLE owner_profile (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
    )
    source.execute(
        "CREATE TABLE autobiographical_event ("
        "id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL "
        "REFERENCES owner_profile(id), detail TEXT NOT NULL)"
    )
    source.execute("INSERT INTO owner_profile VALUES (1, 'creator')")
    source.execute(
        "INSERT INTO autobiographical_event VALUES (7, 1, 'first learned word')"
    )
    source.commit()

    key = "test-only-encryption-key-for-local-recovery"
    archive_path = tmp_path / "chappie-turso-daily.zip"
    report = create_backup_archive(source, archive_path, key)
    assert report["encrypted"] is True
    assert report["verified_after_packaging"] is True

    recovery = restore_daily_artifact(tmp_path, key)

    assert recovery["success"] is True
    assert recovery["table_count"] == 2
    assert recovery["total_rows"] == 2
    assert recovery["integrity_check"] == "ok"
    assert recovery["foreign_key_violations"] == 0
    assert recovery["destination"] == "disposable in-memory SQLite"
    assert recovery["production_database_contacted"] is False
    source.close()
