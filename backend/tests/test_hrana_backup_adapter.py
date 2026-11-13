import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.hrana_backup import HranaTransactionConnection, describe_hrana_error


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

    cursor = connection.execute("SELECT * FROM sqlite_master")
    assert cursor.description[0][0] == "type"
    assert cursor.fetchall()[0][1] == "memories"

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
        "SELECT 1; DELETE FROM memories",
    ],
)
def test_hrana_backup_adapter_rejects_non_select_sql(sql):
    transaction = _Transaction()
    connection = HranaTransactionConnection(transaction)

    with pytest.raises(PermissionError):
        connection.execute(sql)

    assert transaction.statements == []


def test_hrana_adapter_uses_the_same_caller_owned_transaction(tmp_path):
    transaction = _Transaction()
    connection = HranaTransactionConnection(transaction)

    from storage.logical_backup import export_logical_backup, verify_logical_backup

    destination = tmp_path / "hrana-backup-test.json"
    try:
        report = export_logical_backup(
            connection, destination, manage_snapshot=False
        )
        assert report["verified"] is True
        assert report["total_rows"] == 1
        assert verify_logical_backup(destination)["valid"] is True
        assert len(transaction.statements) == 2
    finally:
        destination.unlink(missing_ok=True)
        destination.with_suffix(destination.suffix + ".sha256").unlink(missing_ok=True)


def test_hrana_error_summary_exposes_status_without_request_credentials():
    class HandshakeError(Exception):
        status = 400
        message = "Invalid response status"

        def __str__(self):
            return "wss://user:secret@example.invalid?token=private"

    details = describe_hrana_error(HandshakeError())
    assert details == {
        "error_type": "HandshakeError",
        "status": 400,
        "reason": "Invalid response status",
    }
    assert "secret" not in repr(details)
    assert "private" not in repr(details)
