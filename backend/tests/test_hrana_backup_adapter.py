import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.hrana_backup import HranaTransactionConnection


class _Result:
    def __init__(self, columns, rows):
        self.columns = tuple(columns)
        self.rows = [tuple(row) for row in rows]


class _Transaction:
    def __init__(self):
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        if "sqlite_master" in sql:
            return _Result(
                ("type", "name", "tbl_name", "sql"),
                [("table", "memories", "memories", "CREATE TABLE memories (id INTEGER, note TEXT)")],
            )
        if 'FROM "memories"' in sql:
            return _Result(("id", "note"), [(1, "private fixture")])
        raise AssertionError("Unexpected SQL: " + sql)


def test_hrana_adapter_normalizes_result_sets_for_logical_backup():
    transaction = _Transaction()
    connection = HranaTransactionConnection(transaction)

    cursor = connection.execute("SELECT 1 AS probe")
    assert cursor.description[0][0] == "probe"
    assert cursor.fetchall() == []

    result = connection.execute('SELECT * FROM "memories"')
    assert result.description[0][0] == "id"
    assert result.fetchall() == [(1, "private fixture")]


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN",
        "INSERT INTO memories VALUES (2, 'not allowed')",
        "UPDATE memories SET note='not allowed'",
        "DELETE FROM memories",
        "PRAGMA query_only=OFF",
    ],
)
def test_hrana_backup_adapter_rejects_non_select_sql(sql):
    transaction = _Transaction()
    connection = HranaTransactionConnection(transaction)

    with pytest.raises(PermissionError):
        connection.execute(sql)

    assert transaction.statements == []


def test_hrana_adapter_uses_the_same_caller_owned_transaction():
    transaction = _Transaction()
    connection = HranaTransactionConnection(transaction)

    connection.execute("SELECT * FROM sqlite_master")
    connection.execute('SELECT * FROM "memories"')

    assert len(transaction.statements) == 2
