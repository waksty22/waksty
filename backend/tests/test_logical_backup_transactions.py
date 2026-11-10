import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.logical_backup import export_logical_backup, verify_logical_backup


def _database():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, note TEXT)")
    connection.execute("INSERT INTO memories(note) VALUES ('private test fixture')")
    connection.commit()
    return connection


def test_logical_backup_keeps_default_sqlite_savepoint(tmp_path):
    connection = _database()
    try:
        destination = tmp_path / "sqlite.json"
        report = export_logical_backup(connection, destination)

        assert report["verified"] is True
        assert report["total_rows"] == 1
        assert connection.in_transaction is False
        assert verify_logical_backup(destination)["valid"] is True
    finally:
        connection.close()


def test_logical_backup_can_use_caller_managed_transaction(tmp_path):
    connection = _database()
    try:
        connection.execute("BEGIN")
        destination = tmp_path / "turso-transaction.json"

        report = export_logical_backup(
            connection,
            destination,
            manage_snapshot=False,
        )

        # The caller's transaction remains open after export, so a libSQL
        # transaction adapter can commit/rollback the complete read snapshot.
        assert connection.in_transaction is True
        assert report["verified"] is True
        assert report["total_rows"] == 1
        assert verify_logical_backup(destination)["valid"] is True
        connection.commit()
        assert connection.in_transaction is False
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
