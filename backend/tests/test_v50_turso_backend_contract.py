"""V50.41 — explicit DB-API and backend-boundary contracts."""
from pathlib import Path
import ast
import sqlite3
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest
from storage.libsql_adapter import (
    CompatCursor,
    CompatRow,
    LibSQLConnectionAdapter,
    adapt_libsql_connection,
)
from storage.connection_factory import (
    StorageSettings,
    open_sqlite_application_connection,
)


class FakeCursor:
    description = (("id",), ("label",))

    def __init__(self, rows=(), lastrowid=17, rowcount=1):
        self.rows = list(rows)
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, size=1):
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows


class FakeNativeConnection:
    def __init__(self):
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.scripts = []
        self.executed = []

    def execute(self, sql, parameters=()):
        self.executed.append((sql, parameters))
        if sql == "SELECT id, label FROM sample":
            return FakeCursor([(1, "Chappie"), (2, "Nova")])
        if sql == "SELECT 1":
            return FakeCursor([(1,)])
        return FakeCursor([])

    def executemany(self, sql, parameters):
        self.executed.append((sql, list(parameters)))
        return FakeCursor([])

    def executescript(self, script):
        self.scripts.append(script)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_compat_row_supports_named_and_positional_access():
    row = CompatRow((7, "Chappie"), ("id", "name"))
    assert row[0] == 7
    assert row["id"] == 7
    assert row["NAME"] == "Chappie"
    assert row.keys() == ["id", "name"]
    assert row.as_dict() == {"id": 7, "name": "Chappie"}


def test_adapter_normalizes_cursor_rows_and_iteration():
    native = FakeNativeConnection()
    db = adapt_libsql_connection(native)
    cursor = db.execute("SELECT id, label FROM sample")
    assert cursor.lastrowid is None
    assert cursor.rowcount == 1
    rows = list(cursor)
    assert rows[0]["label"] == "Chappie"
    assert rows[1][0] == 2


def test_adapter_preserves_insert_lastrowid_but_not_stale_select_metadata():
    native = FakeNativeConnection()
    db = adapt_libsql_connection(native)
    inserted = db.execute("INSERT INTO sample(label) VALUES (?)", ("Chappie",))
    selected = db.execute("SELECT 1")
    updated = db.execute("UPDATE sample SET label='Nova'")
    assert inserted.lastrowid == 17
    assert selected.lastrowid is None
    assert updated.lastrowid is None


def test_executemany_does_not_publish_native_lastrowid():
    db = adapt_libsql_connection(FakeNativeConnection())
    cursor = db.executemany("INSERT INTO sample(label) VALUES (?)", [("A",), ("B",)])
    assert cursor.lastrowid is None


def test_adapter_exposes_fetchone_fetchall_fetchmany():
    cursor = CompatCursor(FakeCursor([(1, "a"), (2, "b"), (3, "c")]))
    assert cursor.fetchone()["id"] == 1
    assert cursor.fetchmany(1)[0]["label"] == "b"
    assert cursor.fetchall()[0]["id"] == 3


def test_context_manager_commits_or_rolls_back_without_closing():
    native = FakeNativeConnection()
    db = adapt_libsql_connection(native)
    with db:
        db.execute("SELECT 1")
    assert native.commits == 1
    assert native.closed is False

    with pytest.raises(RuntimeError):
        with db:
            raise RuntimeError("rollback")
    assert native.rollbacks == 1
    assert native.closed is False


def test_adapter_close_is_idempotent_and_closed_use_fails():
    native = FakeNativeConnection()
    db = adapt_libsql_connection(native)
    db.close()
    db.close()
    assert native.closed
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_executescript_requires_native_driver_support():
    class NoScriptConnection(FakeNativeConnection):
        executescript = None

    db = adapt_libsql_connection(NoScriptConnection())
    with pytest.raises(NotImplementedError, match="executescript"):
        db.executescript("CREATE TABLE example(id INTEGER)")


def test_adapter_does_not_claim_sqlite_backup_api():
    db = adapt_libsql_connection(FakeNativeConnection())
    assert not callable(getattr(db, "backup", None))


def test_turso_remains_blocked_at_application_boundary():
    settings = StorageSettings(
        backend="turso",
        turso_database_url="libsql://example.turso.io",
        turso_auth_token="placeholder-only",
    )
    with pytest.raises(RuntimeError, match="Turso n'est pas encore activé"):
        open_sqlite_application_connection(settings)
