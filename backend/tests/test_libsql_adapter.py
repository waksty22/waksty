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

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.lstrip().upper().startswith("SELECT"):
            return FakeCursor([(3, "Chappie")])
        return FakeCursor([], lastrowid=42)

    def executemany(self, sql, params):
        self.calls.append((sql, list(params)))
        return FakeCursor([], lastrowid=0, rowcount=2)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_compat_row_supports_index_and_name_access():
    row = CompatRow((10, "memory"), ("id", "kind"))

    assert row[0] == 10
    assert row["kind"] == "memory"
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


def test_executescript_sends_statements_sequentially():
    raw = FakeConnection()
    db = LibSQLConnectionAdapter(raw)

    db.executescript(
        """
        CREATE TABLE first_table (id INTEGER PRIMARY KEY);
        CREATE TABLE second_table (id INTEGER PRIMARY KEY);
        """
    )

    assert len(raw.calls) == 2
    assert raw.calls[0][0].lstrip().startswith("CREATE TABLE first_table")
    assert raw.calls[1][0].lstrip().startswith("CREATE TABLE second_table")


def test_context_manager_commits_and_closes_on_success():
    raw = FakeConnection()
    with LibSQLConnectionAdapter(raw) as db:
        db.execute("SELECT id, label FROM sample")

    assert raw.commits == 1
    assert raw.rollbacks == 0
    assert raw.closed is True


def test_context_manager_rolls_back_and_closes_on_error():
    raw = FakeConnection()

    try:
        with LibSQLConnectionAdapter(raw):
            raise RuntimeError("expected")
    except RuntimeError:
        pass

    assert raw.commits == 0
    assert raw.rollbacks == 1
    assert raw.closed is True
