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



def test_sqlite_factory_persists_data_after_connection_is_reopened(tmp_path):
    database_path = tmp_path / "durable" / "chappie.sqlite3"
    first = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(database_path))
    )
    try:
        first.execute(
            "CREATE TABLE durable_memory (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"
        )
        first.execute(
            "INSERT INTO durable_memory(content) VALUES (?)",
            ("souvenir conservé après fermeture",),
        )
        first.commit()
    finally:
        first.close()

    second = open_storage_connection(
        StorageSettings(backend="sqlite", sqlite_path=str(database_path))
    )
    try:
        row = second.execute(
            "SELECT content FROM durable_memory WHERE id=1"
        ).fetchone()
        assert row["content"] == "souvenir conservé après fermeture"
    finally:
        second.close()
