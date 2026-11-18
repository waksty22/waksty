from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.inspect_persistence_inventory import inspect_sqlite_database


def test_inventory_is_read_only_and_does_not_expose_row_content(tmp_path: Path) -> None:
    database = tmp_path / "chappie.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL
        );
        INSERT INTO conversations(user_id, message)
        VALUES ('creator', 'PRIVATE_CHAT_SENTINEL');
        INSERT INTO memories(content)
        VALUES ('PRIVATE_MEMORY_SENTINEL');
    """)
    connection.commit()
    connection.close()

    before = database.read_bytes()
    report = inspect_sqlite_database(database)
    after = database.read_bytes()

    rendered = json.dumps(report)
    assert before == after
    assert report["read_only"] is True
    assert report["database_contents_exposed"] is False
    assert report["total_rows"] == 2
    assert {table["table"]: table["row_count"] for table in report["tables"]}[
        "conversations"
    ] == 1
    assert "PRIVATE_CHAT_SENTINEL" not in rendered
    assert "PRIVATE_MEMORY_SENTINEL" not in rendered
    assert report["integrity_check"]["ok"] is True


def test_inventory_fingerprints_change_when_table_content_changes(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO memories(value) VALUES ('first')")
    connection.commit()
    connection.close()

    first = inspect_sqlite_database(database)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE memories SET value='second' WHERE id=1")
    connection.commit()
    connection.close()
    second = inspect_sqlite_database(database)

    assert first["schema_sha256"] == second["schema_sha256"]
    assert first["tables"][0]["content_sha256"] != second["tables"][0]["content_sha256"]


def test_inventory_rejects_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    try:
        inspect_sqlite_database(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("A missing database must be rejected")
