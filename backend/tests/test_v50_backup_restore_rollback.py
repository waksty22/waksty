"""Backup, restore and rollback tests using temporary local SQLite files."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from storage.backup import create_verified_backup, restore_verified_backup


def _read_value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT value FROM app_state WHERE id=1"
        ).fetchone()[0]
    finally:
        connection.close()


def _write_value(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE app_state SET value=? WHERE id=1", (value,)
        )
        connection.commit()
    finally:
        connection.close()


def test_verified_backup_restore_and_rollback(tmp_path):
    database = tmp_path / "chappie.sqlite3"
    backup = tmp_path / "backups" / "known-good.sqlite3"

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE app_state (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_state(id, value) VALUES (1, 'before-change')"
        )
        connection.commit()
    finally:
        connection.close()

    backup_result = create_verified_backup(database, backup)
    assert backup_result["integrity"] == "ok"
    assert backup_result["sha256"]
    assert backup_result["size_bytes"] > 0
    assert _read_value(backup) == "before-change"

    # Simulate a later application write, then restore the known-good copy.
    _write_value(database, "after-change")
    assert _read_value(database) == "after-change"

    restore_result = restore_verified_backup(backup, database)
    assert restore_result["integrity"] == "ok"
    assert _read_value(database) == "before-change"

    # The pre-restore state is preserved and can itself be restored.
    rollback = Path(restore_result["rollback_path"])
    assert rollback.exists()
    assert _read_value(rollback) == "after-change"

    rollback_result = restore_verified_backup(rollback, database)
    assert rollback_result["integrity"] == "ok"
    assert _read_value(database) == "after-change"


def test_corrupt_backup_is_rejected_without_touching_target(tmp_path):
    database = tmp_path / "active.sqlite3"
    corrupt_backup = tmp_path / "corrupt.sqlite3"

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE app_state (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_state(id, value) VALUES (1, 'must-survive')"
        )
        connection.commit()
    finally:
        connection.close()

    corrupt_backup.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        restore_verified_backup(corrupt_backup, database)

    assert _read_value(database) == "must-survive"
    assert not list(tmp_path.glob("active.sqlite3.rollback-*.sqlite3"))


def test_backup_cannot_overwrite_the_live_database(tmp_path):
    database = tmp_path / "same.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="distinct"):
        create_verified_backup(database, database)
    with pytest.raises(ValueError, match="distinct"):
        restore_verified_backup(database, database)
