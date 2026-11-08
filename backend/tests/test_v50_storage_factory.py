from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from storage.connection_factory import (
    StorageSettings,
    open_storage_connection,
    open_sqlite_application_connection,
)


def test_factory_keeps_sqlite_as_default_when_environment_is_unset(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("CHAPPIE_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("CHAPPIE_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    settings = StorageSettings.from_env()
    assert settings.backend == "sqlite"

    settings = StorageSettings(
        backend=settings.backend,
        sqlite_path=str(tmp_path / "chappie.sqlite3"),
    )
    db = open_storage_connection(settings)
    try:
        assert isinstance(db, sqlite3.Connection)
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO sample(value) VALUES (?)", ("persisted",))
        db.commit()
        assert db.execute("SELECT value FROM sample").fetchone()["value"] == "persisted"
    finally:
        db.close()


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "postgres")
    with pytest.raises(ValueError, match="sqlite ou turso"):
        StorageSettings.from_env()


def test_turso_requires_both_credentials_without_opening_a_connection():
    settings = StorageSettings(
        backend="turso",
        turso_database_url="libsql://example.turso.io",
        turso_auth_token="",
    )
    with pytest.raises(ValueError, match="TURSO_DATABASE_URL"):
        open_storage_connection(settings)


def test_sqlite_factory_does_not_read_turso_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://unused.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "unused-secret")
    db = open_storage_connection(
        StorageSettings(
            backend="sqlite",
            sqlite_path=str(tmp_path / "local.sqlite3"),
        )
    )
    try:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    finally:
        db.close()

def test_factory_uses_the_same_data_dir_and_filename_as_server(monkeypatch, tmp_path):
    active_dir = tmp_path / "active-chappie-data"
    competing_path = tmp_path / "different-empty-database.sqlite3"
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(active_dir))
    # A legacy/accidental second path variable must not split the app and
    # factory onto different SQLite files.
    monkeypatch.setenv("CHAPPIE_SQLITE_PATH", str(competing_path))
    monkeypatch.delenv("CHAPPIE_STORAGE_BACKEND", raising=False)

    settings = StorageSettings.from_env()

    assert settings.backend == "sqlite"
    assert Path(settings.sqlite_path) == (
        active_dir.resolve() / "chappie_v16.sqlite3"
    )
    assert Path(settings.sqlite_path) != competing_path

def test_application_connection_helper_opens_sqlite_only(tmp_path):
    settings = StorageSettings(
        backend="sqlite",
        sqlite_path=str(tmp_path / "server.sqlite3"),
    )
    db = open_sqlite_application_connection(settings)
    try:
        assert isinstance(db, sqlite3.Connection)
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        db.close()


def test_application_connection_helper_fails_closed_for_turso():
    settings = StorageSettings(
        backend="turso",
        turso_database_url="libsql://example.turso.io",
        turso_auth_token="test-token",
    )
    with pytest.raises(RuntimeError, match="Turso n'est pas encore activé"):
        open_sqlite_application_connection(settings)

