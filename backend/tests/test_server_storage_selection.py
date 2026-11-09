import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_server_db_connection_uses_factory_and_configured_db_path(
    monkeypatch, tmp_path
):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CHAPPIE_SQLITE_PATH", raising=False)
    database_path = tmp_path / "actual" / "chappie.sqlite3"
    monkeypatch.setattr(server, "DB_PATH", database_path)

    connection = server.db_connection()
    try:
        connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        connection.commit()
        assert database_path.is_file()
        assert connection.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
    finally:
        connection.close()


def test_server_refuses_turso_startup_without_cutover_marker(monkeypatch):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "turso")
    monkeypatch.delenv("CHAPPIE_TURSO_CUTOVER_READY", raising=False)

    with pytest.raises(RuntimeError, match="CHAPPIE_TURSO_CUTOVER_READY"):
        server.init_db()


def test_persistent_sqlite_cutover_triggers_reject_insert_update_delete():
    import sqlite3
    import server

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, label TEXT)")
        connection.execute("INSERT INTO probe(id, label) VALUES (1, 'existing')")
        connection.execute(
            "CREATE TABLE chappie_storage_migration_state "
            "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO chappie_storage_migration_state VALUES "
            "('sqlite-to-turso-v50.55', 'pending_cutover', 't1')"
        )
        count = server._install_sqlite_cutover_write_guards(connection)
        assert count == 3

        with pytest.raises(sqlite3.IntegrityError, match="pending Turso cutover"):
            connection.execute("INSERT INTO probe(label) VALUES ('new')")
        with pytest.raises(sqlite3.IntegrityError, match="pending Turso cutover"):
            connection.execute("UPDATE probe SET label='changed' WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="pending Turso cutover"):
            connection.execute("DELETE FROM probe WHERE id=1")
    finally:
        connection.close()


def test_local_pending_cutover_marker_is_detected_after_database_reopen(
    monkeypatch, tmp_path
):
    import sqlite3
    import server

    database_path = tmp_path / "chappie.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE chappie_storage_migration_state "
        "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO chappie_storage_migration_state VALUES "
        "('sqlite-to-turso-v50.55', 'pending_cutover', 't1')"
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(server, "DB_PATH", database_path)
    assert server._local_migration_pending_cutover() is True
