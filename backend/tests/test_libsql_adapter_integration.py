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

def test_real_libsql_cursor_reports_dml_rowcount(tmp_path):
    """Verify sqlite3-compatible rowcount against the real libsql driver."""
    libsql = pytest.importorskip("libsql")
    database_path = tmp_path / "rowcount-integration.db"
    connection = adapt_libsql_connection(
        libsql.connect(database=str(database_path))
    )
    try:
        connection.execute(
            "CREATE TABLE rowcount_probe "
            "(id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO rowcount_probe(status) VALUES (?)",
            [("pending",), ("pending",), ("done",)],
        )
        connection.commit()

        updated = connection.execute(
            "UPDATE rowcount_probe SET status=? WHERE status=?",
            ("done", "pending"),
        )
        assert updated.rowcount == 2

        deleted = connection.execute(
            "DELETE FROM rowcount_probe WHERE status=?",
            ("done",),
        )
        assert deleted.rowcount == 3

        unchanged = connection.execute(
            "UPDATE rowcount_probe SET status=? WHERE id < 0",
            ("missing",),
        )
        assert unchanged.rowcount == 0
        connection.commit()
    finally:
        connection.close()



def test_real_libsql_dml_rowcount_matches_sqlite_dbapi(tmp_path):
    """Verify DML rowcount on the native driver used by the opt-in backend."""
    libsql = pytest.importorskip("libsql")
    database_path = tmp_path / "rowcount-contract.db"
    connection = adapt_libsql_connection(
        libsql.connect(database=str(database_path))
    )

    try:
        connection.execute(
            "CREATE TABLE rowcount_probe "
            "(id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        connection.commit()

        inserted = connection.execute(
            "INSERT INTO rowcount_probe(label) VALUES (?)",
            ("first",),
        )
        assert inserted.rowcount == 1
        assert inserted.lastrowid == 1
        connection.commit()

        updated = connection.execute(
            "UPDATE rowcount_probe SET label=? WHERE id=?",
            ("updated", 1),
        )
        assert updated.rowcount == 1
        connection.commit()

        unmatched = connection.execute(
            "UPDATE rowcount_probe SET label=? WHERE id=?",
            ("missing", 999),
        )
        assert unmatched.rowcount == 0
        connection.commit()

        deleted = connection.execute(
            "DELETE FROM rowcount_probe WHERE id=?",
            (1,),
        )
        assert deleted.rowcount == 1
        connection.commit()
    finally:
        connection.close()


def test_full_chappie_schema_initializes_and_persists_on_libsql(
    monkeypatch, tmp_path
):
    """Exercise every Chappie schema initializer through the production adapter."""
    libsql = pytest.importorskip("libsql")
    import server as chappie_server

    database_path = tmp_path / "chappie-full-schema.db"
    settings = chappie_server.StorageSettings(
        backend="turso",
        turso_database_url="libsql://isolated.invalid",
        turso_auth_token="isolated-test-token",
    )
    monkeypatch.setenv("CHAPPIE_TURSO_CUTOVER_READY", "1")
    monkeypatch.delenv("CHAPPIE_TURSO_FRESH_START", raising=False)
    monkeypatch.delenv("CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA", raising=False)
    monkeypatch.setattr(
        chappie_server.StorageSettings,
        "from_env",
        classmethod(lambda cls: settings),
    )
    # The startup gate is satisfied locally; all actual SQL stays in a
    # temporary file-backed libsql database, never in the configured Turso DB.
    monkeypatch.setattr(
        chappie_server,
        "_remote_turso_migration_completed",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        chappie_server,
        "db_connection",
        lambda: adapt_libsql_connection(
            libsql.connect(database=str(database_path)),
            close_on_context_exit=True,
        ),
    )

    chappie_server.init_db()

    writer = adapt_libsql_connection(
        libsql.connect(database=str(database_path)),
        close_on_context_exit=True,
    )
    with writer as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "conversations",
            "memories",
            "personal_vocabulary",
            "sensory_observations",
            "autobiographical_events",
            "emotional_state",
            "skills",
            "goals",
            "voice_profiles",
        }
        assert required.issubset(tables)
        db.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("creator", "user", "premier souvenir de test", "2026-11-16T00:00:00+00:00"),
        )

    reader = adapt_libsql_connection(
        libsql.connect(database=str(database_path)),
        close_on_context_exit=True,
    )
    with reader as db:
        row = db.execute(
            "SELECT content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            ("creator",),
        ).fetchone()
        assert row is not None
        assert row["content"] == "premier souvenir de test"




def test_context_manager_rolls_back_and_closes_when_commit_fails():
    class FailingCommitConnection:
        def __init__(self):
            self.rollback_calls = 0
            self.close_calls = 0

        def commit(self):
            raise RuntimeError("commit failed")

        def rollback(self):
            self.rollback_calls += 1

        def close(self):
            self.close_calls += 1

    native = FailingCommitConnection()
    connection = adapt_libsql_connection(
        native,
        close_on_context_exit=True,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        with connection:
            pass

    assert native.rollback_calls == 1
    assert native.close_calls == 1
    with pytest.raises(Exception, match="closed database"):
        connection.execute("SELECT 1")



def test_context_manager_preserves_body_error_when_rollback_fails():
    class FailingRollbackConnection:
        def __init__(self):
            self.rollback_calls = 0
            self.close_calls = 0

        def commit(self):
            raise AssertionError("commit must not run after body failure")

        def rollback(self):
            self.rollback_calls += 1
            raise RuntimeError("rollback failed")

        def close(self):
            self.close_calls += 1

    native = FailingRollbackConnection()
    connection = adapt_libsql_connection(
        native,
        close_on_context_exit=True,
    )

    with pytest.raises(ValueError, match="original body failure"):
        with connection:
            raise ValueError("original body failure")

    assert native.rollback_calls == 1
    assert native.close_calls == 1
    with pytest.raises(Exception, match="closed database"):
        connection.execute("SELECT 1")


def test_context_manager_preserves_body_error_when_close_fails():
    class FailingCloseConnection:
        def __init__(self):
            self.rollback_calls = 0
            self.close_calls = 0

        def commit(self):
            raise AssertionError("commit must not run after body failure")

        def rollback(self):
            self.rollback_calls += 1

        def close(self):
            self.close_calls += 1
            raise RuntimeError("close failed")

    native = FailingCloseConnection()
    connection = adapt_libsql_connection(native, close_on_context_exit=True)

    with pytest.raises(ValueError, match="original body failure"):
        with connection:
            raise ValueError("original body failure")

    assert native.rollback_calls == 1
    assert native.close_calls == 1


def test_context_manager_preserves_commit_error_when_close_fails():
    class FailingCommitAndCloseConnection:
        def __init__(self):
            self.rollback_calls = 0
            self.close_calls = 0

        def commit(self):
            raise RuntimeError("commit failed")

        def rollback(self):
            self.rollback_calls += 1

        def close(self):
            self.close_calls += 1
            raise RuntimeError("close failed")

    native = FailingCommitAndCloseConnection()
    connection = adapt_libsql_connection(native, close_on_context_exit=True)

    with pytest.raises(RuntimeError, match="commit failed"):
        with connection:
            pass

    assert native.rollback_calls == 1
    assert native.close_calls == 1


def test_context_manager_surfaces_close_error_after_successful_commit():
    class FailingCloseConnection:
        def __init__(self):
            self.commit_calls = 0
            self.close_calls = 0

        def commit(self):
            self.commit_calls += 1

        def close(self):
            self.close_calls += 1
            raise RuntimeError("close failed")

    native = FailingCloseConnection()
    connection = adapt_libsql_connection(native, close_on_context_exit=True)

    with pytest.raises(RuntimeError, match="close failed"):
        with connection:
            pass

    assert native.commit_calls == 1
    assert native.close_calls == 1
