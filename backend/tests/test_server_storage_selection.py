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


def test_init_db_stays_read_only_when_local_cutover_marker_exists(
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
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    server.init_db()

    assert server.STORAGE_MIGRATION_PENDING_CUTOVER is True
    check = sqlite3.connect(database_path)
    try:
        # init_db returned before executing its ordinary schema initialization.
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='conversations'"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_pre_cutover_cancel_removes_only_marker_and_local_guards(
    monkeypatch, tmp_path
):
    import asyncio
    import sqlite3
    import sys
    import types
    import server

    local_path = tmp_path / "chappie.sqlite3"
    local = sqlite3.connect(local_path)
    local.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, label TEXT)")
    local.execute(
        "CREATE TABLE chappie_storage_migration_state "
        "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    local.execute(
        "INSERT INTO chappie_storage_migration_state VALUES "
        "('sqlite-to-turso-v50.55', 'pending_cutover', 't1')"
    )
    server._install_sqlite_cutover_write_guards(local)
    local.commit()
    local.close()

    remote = sqlite3.connect(":memory:")
    remote.execute(
        "CREATE TABLE chappie_storage_migrations "
        "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL)"
    )
    remote.execute(
        "INSERT INTO chappie_storage_migrations VALUES "
        "('sqlite-to-turso-v50.55', 'completed')"
    )
    remote.commit()

    class FakeLibsqlConnection:
        def execute(self, *args, **kwargs):
            return remote.execute(*args, **kwargs)

        def commit(self):
            return remote.commit()

        def close(self):
            # Keep the in-memory test database available for post-call assertions.
            return None

    fake_libsql = types.SimpleNamespace(
        connect=lambda **kwargs: FakeLibsqlConnection()
    )
    monkeypatch.setitem(sys.modules, "libsql", fake_libsql)
    monkeypatch.setattr(server, "DB_PATH", local_path)
    monkeypatch.setenv("CHAPPIE_ALLOW_SQLITE_ROLLBACK", "1")
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", True)

    payload = server.TursoMigrationCancelRequest(
        confirmation="ANNULER LA BASCULE TURSO"
    )
    result = asyncio.run(
        server.api_storage_migration_cancel(payload, auth="creator")
    )

    assert result["cancelled"] is True
    assert result["turso_data_preserved"] is True
    assert server.STORAGE_MIGRATION_PENDING_CUTOVER is False
    assert remote.execute(
        "SELECT COUNT(*) FROM chappie_storage_migrations"
    ).fetchone()[0] == 0

    local_check = sqlite3.connect(local_path)
    try:
        assert local_check.execute(
            "SELECT status FROM chappie_storage_migration_state"
        ).fetchone()[0] == "cancelled"
        assert local_check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'chappie_migration_guard_%'"
        ).fetchone()[0] == 0
        local_check.execute("INSERT INTO probe(label) VALUES ('resumed')")
        local_check.commit()
    finally:
        local_check.close()
    remote.close()


def test_pre_cutover_cancel_recovers_when_local_marker_was_not_written(
    monkeypatch, tmp_path
):
    import asyncio
    import sqlite3
    import sys
    import types
    import server

    local_path = tmp_path / "chappie.sqlite3"
    local = sqlite3.connect(local_path)
    local.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, label TEXT)")
    local.commit()
    local.close()

    remote_path = tmp_path / "turso.sqlite3"
    remote = sqlite3.connect(remote_path)
    remote.execute(
        "CREATE TABLE chappie_storage_migrations "
        "(migration_key TEXT PRIMARY KEY, status TEXT NOT NULL)"
    )
    remote.execute(
        "INSERT INTO chappie_storage_migrations VALUES "
        "('sqlite-to-turso-v50.55', 'completed')"
    )
    remote.commit()
    remote.close()

    class FakeLibsqlConnection:
        def __init__(self):
            self.connection = sqlite3.connect(remote_path)

        def execute(self, *args, **kwargs):
            return self.connection.execute(*args, **kwargs)

        def commit(self):
            return self.connection.commit()

        def close(self):
            self.connection.close()

    monkeypatch.setitem(
        sys.modules,
        "libsql",
        types.SimpleNamespace(connect=lambda **kwargs: FakeLibsqlConnection()),
    )
    monkeypatch.setattr(server, "DB_PATH", local_path)
    monkeypatch.setenv("CHAPPIE_ALLOW_SQLITE_ROLLBACK", "1")
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", True)

    payload = server.TursoMigrationCancelRequest(
        confirmation="ANNULER LA BASCULE TURSO"
    )
    result = asyncio.run(
        server.api_storage_migration_cancel(payload, auth="creator")
    )

    assert result["cancelled"] is True
    assert server.STORAGE_MIGRATION_PENDING_CUTOVER is False

    local_check = sqlite3.connect(local_path)
    try:
        local_check.execute("INSERT INTO probe(label) VALUES ('resumed')")
        local_check.commit()
    finally:
        local_check.close()

    remote_check = sqlite3.connect(remote_path)
    try:
        assert remote_check.execute(
            "SELECT COUNT(*) FROM chappie_storage_migrations"
        ).fetchone()[0] == 0
    finally:
        remote_check.close()


def test_missing_local_sqlite_and_missing_turso_credentials_fail_closed(
    monkeypatch,
):
    import server

    monkeypatch.setenv("CHAPPIE_ALLOW_TURSO_MIGRATION", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="accès Turso incomplet"):
        server._remote_turso_migration_completed()


def test_missing_local_sqlite_and_missing_remote_marker_fail_closed(
    monkeypatch, tmp_path,
):
    import sqlite3
    import sys
    import types
    import server

    remote_path = tmp_path / "empty-turso.sqlite3"
    remote = sqlite3.connect(remote_path)
    remote.close()

    monkeypatch.setitem(
        sys.modules,
        "libsql",
        types.SimpleNamespace(
            connect=lambda **kwargs: sqlite3.connect(remote_path)
        ),
    )
    monkeypatch.setenv("CHAPPIE_ALLOW_TURSO_MIGRATION", "1")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")

    with pytest.raises(RuntimeError, match="Base SQLite absente"):
        server._remote_turso_migration_completed()
