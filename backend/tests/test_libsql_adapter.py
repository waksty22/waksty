from storage.libsql_adapter import (
    CompatRow,
    LibSQLConnectionAdapter,
    adapt_libsql_connection,
)


class FakeCursor:
    def __init__(self, rows=(), names=("id", "label"), lastrowid=7, rowcount=1):
        self.description = tuple((name, None, None, None, None, None, None) for name in names)
        self._rows = list(rows)
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchmany(self, size=1):
        rows, self._rows = self._rows[:size], self._rows[size:]
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.scripts = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.lstrip().upper().startswith("SELECT"):
            return FakeCursor([(3, "Chappie")])
        return FakeCursor([], lastrowid=42)

    def executemany(self, sql, params):
        self.calls.append((sql, list(params)))
        return FakeCursor([], lastrowid=0, rowcount=2)

    def executescript(self, script):
        self.scripts.append(script)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_compat_row_supports_index_and_case_insensitive_name_access():
    row = CompatRow((10, "memory"), ("id", "kind"))

    assert row[0] == 10
    assert row["kind"] == "memory"
    assert row["KIND"] == "memory"
    assert row.keys() == ["id", "kind"]
    assert row.as_dict() == {"id": 10, "kind": "memory"}


def test_execute_returns_rows_with_sqlite_style_access():
    raw = FakeConnection()
    db = adapt_libsql_connection(raw)

    row = db.execute("SELECT id, label FROM sample").fetchone()

    assert row[0] == 3
    assert row["label"] == "Chappie"


def test_cursor_exposes_lastrowid_and_rowcount():
    db = LibSQLConnectionAdapter(FakeConnection())
    cursor = db.execute("INSERT INTO sample(label) VALUES (?)", ("x",))

    assert cursor.lastrowid == 42
    assert cursor.rowcount == 1


def test_executemany_forwards_parameters():
    raw = FakeConnection()
    db = LibSQLConnectionAdapter(raw)
    cursor = db.executemany(
        "INSERT INTO sample(label) VALUES (?)",
        [("a",), ("b",)],
    )

    assert cursor.rowcount == 2
    assert raw.calls[-1][1] == [("a",), ("b",)]


def test_executescript_delegates_to_native_driver():
    raw = FakeConnection()
    db = LibSQLConnectionAdapter(raw)
    script = "CREATE TABLE first_table (id INTEGER PRIMARY KEY);"

    db.executescript(script)

    assert raw.scripts == [script]


def test_context_manager_commits_without_closing_connection():
    raw = FakeConnection()
    with LibSQLConnectionAdapter(raw) as db:
        db.execute("SELECT id, label FROM sample")

    assert raw.commits == 1
    assert raw.rollbacks == 0
    assert raw.closed is False


def test_context_manager_rolls_back_without_closing_on_error():
    raw = FakeConnection()

    try:
        with LibSQLConnectionAdapter(raw):
            raise RuntimeError("expected")
    except RuntimeError:
        pass

    assert raw.commits == 0
    assert raw.rollbacks == 1
    assert raw.closed is False


def test_explicit_close_closes_underlying_connection():
    raw = FakeConnection()
    db = LibSQLConnectionAdapter(raw)

    db.close()

    assert raw.closed is True


def test_real_libsql_in_memory_driver_contract():
    """Exercise the actual installed libsql binding without touching Turso."""
    import pytest

    libsql = pytest.importorskip("libsql")
    raw = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(raw)
    try:
        db.executescript(
            """
            CREATE TABLE sample (id INTEGER PRIMARY KEY, label TEXT NOT NULL);
            INSERT INTO sample(label) VALUES ('Chappie');
            """
        )
        row = db.execute(
            "SELECT id, label FROM sample WHERE label = ?", ("Chappie",)
        ).fetchone()

        assert row is not None
        assert row["id"] == 1
        assert row["LABEL"] == "Chappie"
        assert row[0] == 1

        inserted = db.execute(
            "INSERT INTO sample(label) VALUES (?)", ("Nova",)
        )
        assert inserted.lastrowid is not None
        assert db.execute("SELECT COUNT(*) AS total FROM sample").fetchone()["total"] == 2
    finally:
        db.close()


def test_libsql_operational_errors_are_normalized():
    import sqlite3
    import pytest

    class OperationalError(Exception):
        pass

    class ErroringConnection(FakeConnection):
        def execute(self, sql, params=()):
            raise OperationalError("no such table")

    db = LibSQLConnectionAdapter(ErroringConnection())
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        db.execute("SELECT * FROM missing_table")


def test_real_libsql_missing_table_raises_sqlite_compatible_error():
    import sqlite3
    import pytest

    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("SELECT * FROM table_that_does_not_exist")
    finally:
        db.close()


def test_world_model_accepts_libsql_adapter_connection_overload():
    import pytest

    libsql = pytest.importorskip("libsql")
    from world.world_model import get_entity_relations, init_world_tables

    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        init_world_tables(db)
        assert get_entity_relations(db, "creator", "not-yet-created") == []
    finally:
        db.close()



def test_real_libsql_executemany_and_cursor_iteration_contract():
    import pytest

    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        db.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        db.executemany(
            "INSERT INTO events(label) VALUES (?)",
            [("wake",), ("learn",), ("remember",)],
        )
        db.commit()

        cursor = db.execute("SELECT id, label FROM events ORDER BY id")
        first_batch = cursor.fetchmany(2)
        assert [row["label"] for row in first_batch] == ["wake", "learn"]

        remaining = list(cursor)
        assert len(remaining) == 1
        assert remaining[0][1] == "remember"

        empty_cursor = db.execute(
            "SELECT id, label FROM events WHERE id < 0"
        )
        assert empty_cursor.description
        assert empty_cursor.fetchone() is None
        assert empty_cursor.fetchall() == []
    finally:
        db.close()


def test_real_libsql_explicit_rollback_discards_pending_insert():
    import pytest

    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        db.execute(
            "CREATE TABLE transactions_test "
            "(id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        db.commit()

        db.execute(
            "INSERT INTO transactions_test(label) VALUES (?)", ("temporary",)
        )
        db.rollback()

        count = db.execute(
            "SELECT COUNT(*) AS total FROM transactions_test"
        ).fetchone()["total"]
        assert count == 0
    finally:
        db.close()


def test_real_libsql_context_manager_commits_and_rolls_back():
    import pytest

    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        db.execute(
            "CREATE TABLE context_test "
            "(id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        db.commit()

        with db:
            db.execute(
                "INSERT INTO context_test(label) VALUES (?)", ("committed",)
            )
        assert db.execute(
            "SELECT COUNT(*) AS total FROM context_test"
        ).fetchone()["total"] == 1

        try:
            with db:
                db.execute(
                    "INSERT INTO context_test(label) VALUES (?)", ("rolled-back",)
                )
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        rows = db.execute(
            "SELECT label FROM context_test ORDER BY id"
        ).fetchall()
        assert [row["label"] for row in rows] == ["committed"]
    finally:
        db.close()


def test_real_libsql_constraint_error_is_normalized():
    import sqlite3
    import pytest

    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        db.execute(
            "CREATE TABLE unique_test "
            "(id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL)"
        )
        db.execute("INSERT INTO unique_test(label) VALUES (?)", ("same",))
        db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO unique_test(label) VALUES (?)", ("same",))
    finally:
        db.close()
