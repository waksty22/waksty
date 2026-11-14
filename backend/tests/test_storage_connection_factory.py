import sys
from pathlib import Path

import sqlite3
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.connection_factory import StorageSettings, open_storage_connection


def test_settings_follow_chappie_data_dir_when_sqlite_path_is_not_overridden(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CHAPPIE_SQLITE_PATH", raising=False)

    settings = StorageSettings.from_env()

    assert Path(settings.sqlite_path) == tmp_path / "chappie_v16.sqlite3"


def test_sqlite_factory_returns_named_rows_and_creates_parent_directory(tmp_path):
    database_path = tmp_path / "nested" / "chappie.sqlite3"
    connection = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(database_path))
    )
    try:
        connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, label TEXT)")
        connection.execute("INSERT INTO probe(label) VALUES (?)", ("persistent",))
        connection.commit()

        row = connection.execute("SELECT id, label FROM probe").fetchone()

        assert isinstance(row, sqlite3.Row)
        assert row["label"] == "persistent"
        assert database_path.is_file()
    finally:
        connection.close()


def test_turso_factory_fails_closed_when_credentials_are_missing():
    with pytest.raises(ValueError, match="TURSO_DATABASE_URL et TURSO_AUTH_TOKEN"):
        open_storage_connection(
            StorageSettings(
                backend="turso",
                turso_database_url="",
                turso_auth_token="",
            )
        )


def test_storage_backend_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "postgres")
    with pytest.raises(ValueError, match="sqlite ou turso"):
        StorageSettings.from_env()


def test_closing_connection_closes_after_successful_context_exit(tmp_path):
    from storage.connection_factory import ClosingConnection

    raw = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(tmp_path / "closed.db"))
    )
    connection = ClosingConnection(raw)
    with connection as db:
        db.execute("CREATE TABLE probe (value TEXT)")
        db.execute("INSERT INTO probe(value) VALUES ('committed')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_closing_connection_rolls_back_and_closes_after_exception(tmp_path):
    from storage.connection_factory import ClosingConnection

    database_path = tmp_path / "rollback.db"
    raw = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(database_path))
    )
    raw.execute("CREATE TABLE probe (value TEXT)")
    raw.commit()
    connection = ClosingConnection(raw)

    with pytest.raises(RuntimeError, match="abort transaction"):
        with connection as db:
            db.execute("INSERT INTO probe(value) VALUES ('must rollback')")
            raise RuntimeError("abort transaction")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    reopened = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(database_path))
    )
    try:
        assert reopened.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
    finally:
        reopened.close()


def test_closing_connection_closes_local_libsql_after_successful_context_exit(tmp_path):
    import libsql

    from storage.connection_factory import ClosingConnection
    from storage.libsql_adapter import adapt_libsql_connection

    database_path = str(tmp_path / "libsql-closed.db")
    raw = adapt_libsql_connection(libsql.connect(database=database_path))
    connection = ClosingConnection(raw)

    with connection as db:
        db.execute("CREATE TABLE probe (value TEXT)")
        db.execute("INSERT INTO probe(value) VALUES ('committed')")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    reopened = adapt_libsql_connection(libsql.connect(database=database_path))
    try:
        assert reopened.execute("SELECT value FROM probe").fetchone()[0] == "committed"
    finally:
        reopened.close()


def test_closing_connection_rolls_back_and_closes_local_libsql_after_exception(
    tmp_path,
):
    import libsql

    from storage.connection_factory import ClosingConnection
    from storage.libsql_adapter import adapt_libsql_connection

    database_path = str(tmp_path / "libsql-rollback.db")
    initial = adapt_libsql_connection(libsql.connect(database=database_path))
    initial.execute("CREATE TABLE probe (value TEXT)")
    initial.commit()
    initial.close()

    raw = adapt_libsql_connection(libsql.connect(database=database_path))
    connection = ClosingConnection(raw)

    with pytest.raises(RuntimeError, match="abort transaction"):
        with connection as db:
            db.execute("INSERT INTO probe(value) VALUES ('must rollback')")
            raise RuntimeError("abort transaction")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    reopened = adapt_libsql_connection(libsql.connect(database=database_path))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
    finally:
        reopened.close()
