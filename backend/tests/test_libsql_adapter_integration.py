from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.libsql_adapter import LibSQLConnectionAdapter, adapt_libsql_connection


def test_real_libsql_driver_supports_production_adapter_contract(tmp_path):
    libsql = pytest.importorskip("libsql")
    database_path = tmp_path / "adapter-integration.db"
    native = libsql.connect(database=str(database_path))
    connection = adapt_libsql_connection(native)

    try:
        assert isinstance(connection, LibSQLConnectionAdapter)

        # Exercise the native libsql driver, not a sqlite3 stand-in.
        connection.executescript(
            """
            CREATE TABLE adapter_probe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL
            );
            CREATE INDEX idx_adapter_probe_label ON adapter_probe(label);
            """
        )

        inserted = connection.execute(
            "INSERT INTO adapter_probe(label) VALUES (?)",
            ("first",),
        )
        assert inserted.lastrowid == 1
        connection.commit()

        row = connection.execute(
            "SELECT id, label FROM adapter_probe WHERE id=?",
            (1,),
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row["id"] == 1
        assert row["label"] == "first"
        assert row.keys() == ["id", "label"]

        connection.executemany(
            "INSERT INTO adapter_probe(label) VALUES (?)",
            [("second",), ("third",)],
        )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM adapter_probe"
        ).fetchone()[0] == 3

        connection.execute(
            "INSERT INTO adapter_probe(label) VALUES (?)",
            ("must-rollback",),
        )
        connection.rollback()
        assert connection.execute(
            "SELECT COUNT(*) FROM adapter_probe"
        ).fetchone()[0] == 3

        columns = connection.execute(
            "PRAGMA table_info(adapter_probe)"
        ).fetchall()
        assert [column["name"] for column in columns] == ["id", "label"]
    finally:
        connection.close()


def test_real_libsql_file_database_persists_after_connection_reopen(tmp_path):
    """Verify durable local libSQL storage across connection close/reopen."""
    libsql = pytest.importorskip("libsql")
    database_path = tmp_path / "persistent-brain.db"

    first = adapt_libsql_connection(
        libsql.connect(database=str(database_path))
    )
    first.execute(
        "CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"
    )
    first.execute(
        "INSERT INTO memories(content) VALUES (?)",
        ("Chappie se souvient de son premier apprentissage.",),
    )
    first.commit()
    first.close()

    second = adapt_libsql_connection(
        libsql.connect(database=str(database_path))
    )
    try:
        row = second.execute(
            "SELECT content FROM memories WHERE id = ?",
            (1,),
        ).fetchone()
        assert row is not None
        assert row["content"] == (
            "Chappie se souvient de son premier apprentissage."
        )
    finally:
        second.close()
