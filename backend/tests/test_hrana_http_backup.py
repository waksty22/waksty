import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.hrana_backup import HranaTransactionConnection
from storage.hrana_http import HranaHttpClient, HranaHttpError
from storage.logical_backup import (
    export_encrypted_logical_backup,
    verify_encrypted_logical_backup,
)


def _typed(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


class FakeHranaServer:
    def __init__(self):
        self.baton = None
        self.counter = 0
        self.statements = []
        self.active = False
        self.closed = False

    def handle(self, request):
        assert request.url.path == "/v2/pipeline"
        assert request.headers["authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["baton"] == self.baton
        results = []
        for item in body["requests"]:
            if item["type"] == "close":
                self.closed = True
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            sql = item["stmt"]["sql"]
            self.statements.append(sql)
            if sql == "BEGIN":
                self.active = True
                result = {"cols": [], "rows": []}
            elif sql in {"COMMIT", "ROLLBACK"}:
                self.active = False
                result = {"cols": [], "rows": []}
            elif "sqlite_master" in sql:
                result = {
                    "cols": [
                        {"name": "type", "decltype": "TEXT"},
                        {"name": "name", "decltype": "TEXT"},
                        {"name": "tbl_name", "decltype": "TEXT"},
                        {"name": "sql", "decltype": "TEXT"},
                    ],
                    "rows": [[
                        _typed("table"),
                        _typed("memories"),
                        _typed("memories"),
                        _typed("CREATE TABLE memories (id INTEGER, note TEXT)"),
                    ]],
                }
            elif 'FROM "memories"' in sql:
                result = {
                    "cols": [
                        {"name": "id", "decltype": "INTEGER"},
                        {"name": "note", "decltype": "TEXT"},
                    ],
                    "rows": [[_typed(7), _typed("test fixture")]],
                }
            else:
                return httpx.Response(
                    200,
                    json={
                        "baton": self.baton,
                        "results": [{
                            "type": "error",
                            "error": {"message": "no such table", "code": "SQLITE_ERROR"},
                        }],
                    },
                )
            results.append({
                "type": "ok",
                "response": {"type": "execute", "result": result},
            })
        if self.closed:
            self.baton = None
        else:
            self.counter += 1
            self.baton = "opaque-baton-" + str(self.counter)
        return httpx.Response(
            200,
            json={"baton": self.baton, "base_url": None, "results": results},
        )


def _client(server, *, database_url="libsql://example-org.turso.io"):
    http = httpx.Client(transport=httpx.MockTransport(server.handle))
    return HranaHttpClient(database_url, "test-token", http_client=http)


def test_http_v2_backup_uses_one_baton_transaction_and_verifies(tmp_path):
    server = FakeHranaServer()
    client = _client(server)
    transaction = None
    destination = tmp_path / "turso-backup.json.enc"
    try:
        assert client._endpoint == "https://example-org.turso.io/v2/pipeline"
        transaction = client.transaction()
        report = export_encrypted_logical_backup(
            HranaTransactionConnection(transaction),
            destination,
            "test-encryption-key-123",
            manage_snapshot=False,
        )
        transaction.commit()
        assert report["verified"] is True
        assert report["encrypted"] is True
        assert report["total_rows"] == 1
        assert verify_encrypted_logical_backup(
            destination, "test-encryption-key-123"
        )["valid"] is True
        assert server.statements[0] == "BEGIN"
        assert "sqlite_master" in server.statements[1]
        assert 'SELECT * FROM "memories"' == server.statements[2]
        assert server.statements[3] == "COMMIT"
        assert server.closed is True
        assert server.active is False
    finally:
        if transaction is not None and transaction._active:
            transaction.rollback()
        client.close()


def test_http_v2_transaction_rolls_back_and_closes_stream():
    server = FakeHranaServer()
    client = _client(server)
    transaction = None
    try:
        transaction = client.transaction()
        transaction.rollback()
        assert server.statements == ["BEGIN", "ROLLBACK"]
        assert server.closed is True
        assert server.active is False
    finally:
        client.close()


def test_http_v2_rejects_non_select_before_network_request():
    server = FakeHranaServer()
    client = _client(server)
    transaction = None
    try:
        transaction = client.transaction()
        with pytest.raises(PermissionError):
            HranaTransactionConnection(transaction).execute(
                "DELETE FROM memories"
            )
        assert server.statements == ["BEGIN"]
        transaction.rollback()
    finally:
        client.close()


def test_http_transport_error_does_not_disclose_database_url_or_token():
    def fail(_request):
        return httpx.Response(400, text="bad handshake")

    http = httpx.Client(transport=httpx.MockTransport(fail))
    client = HranaHttpClient(
        "libsql://private-db.turso.io", "super-secret-token", http_client=http
    )
    try:
        with pytest.raises(HranaHttpError) as captured:
            client.transaction()
        message = str(captured.value)
        assert "private-db" not in message
        assert "super-secret-token" not in message
        assert captured.value.status == 400
    finally:
        client.close()


def test_http_v2_decodes_null_integer_float_text_and_blob():
    from storage.hrana_http import HranaHttpResult

    result = HranaHttpResult({
        "cols": [{"name": "n"}, {"name": "i"}, {"name": "f"}, {"name": "t"}, {"name": "b"}],
        "rows": [[
            {"type": "null"},
            {"type": "integer", "value": "9223372036854775807"},
            {"type": "float", "value": 1.25},
            {"type": "text", "value": "hello"},
            {"type": "blob", "base64": "AAEC"},
        ]],
    })
    assert result.columns == ("n", "i", "f", "t", "b")
    assert result.rows == [(None, 9223372036854775807, 1.25, "hello", bytes([0, 1, 2]))]


def test_hrana_write_transaction_encodes_typed_parameters_without_weakening_read_adapter():
    from storage.hrana_backup import HranaRestoreConnection
    from storage.hrana_http import HranaHttpResult

    class WriteTransaction:
        def __init__(self):
            self.calls = []
            self.committed = False
            self.rolled_back = False

        def execute_write(self, sql, args=()):
            self.calls.append((sql, tuple(args)))
            if sql.startswith("SELECT"):
                return HranaHttpResult({
                    "cols": [{"name": "count"}],
                    "rows": [{"type": "integer", "value": "1"}],
                })
            return HranaHttpResult({"cols": [], "rows": []})

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    transaction = WriteTransaction()
    connection = HranaRestoreConnection(transaction)
    connection.execute("INSERT INTO t VALUES (?, ?, ?)", (1, "note", b"\\x00"))
    cursor = connection.execute("SELECT COUNT(*) FROM t")
    assert cursor.fetchone() == (1,)
    connection.executemany("INSERT INTO t VALUES (?)", [(2,), (3,)])
    connection.commit()
    assert transaction.committed is True
    assert connection.in_transaction is False
    assert len(transaction.calls) == 4

    # The existing backup adapter remains strictly read-only.
    readonly = HranaTransactionConnection(transaction)
    with pytest.raises(PermissionError):
        readonly.execute("DELETE FROM t")


def test_hrana_database_identity_is_normalized_and_rejects_credentials():
    from storage.hrana_http import database_identity

    assert database_identity("libsql://CHAPPIE-TEST.turso.io") == "chappie-test.turso.io"
    with pytest.raises(ValueError):
        database_identity("libsql://user:secret@chappie-test.turso.io")


def test_guarded_restore_refuses_production_or_wrong_host_before_network():
    from storage.hrana_http import open_guarded_restore_transaction

    def unexpected_request(_request):
        raise AssertionError("No network request is allowed for a rejected target")

    http = httpx.Client(transport=httpx.MockTransport(unexpected_request))
    try:
        for expected, production in [
            ("chappie-db.turso.io", "chappie-db.turso.io"),
            ("another-test.turso.io", "chappie-db.turso.io"),
        ]:
            with pytest.raises(PermissionError):
                open_guarded_restore_transaction(
                    "libsql://chappie-db.turso.io",
                    "test-token",
                    expected_target_identity=expected,
                    production_identity=production,
                    http_client=http,
                )
    finally:
        http.close()


def test_guarded_restore_opens_transaction_only_for_exact_test_host():
    from storage.hrana_http import open_guarded_restore_transaction

    server = FakeHranaServer()
    http = httpx.Client(transport=httpx.MockTransport(server.handle))
    client, transaction = open_guarded_restore_transaction(
        "libsql://isolated-test.turso.io",
        "test-token",
        expected_target_identity="isolated-test.turso.io",
        production_identity="chappie-db.turso.io",
        http_client=http,
    )
    try:
        assert server.statements == ["BEGIN"]
        transaction.rollback()
        assert server.statements == ["BEGIN", "ROLLBACK"]
        assert server.closed is True
    finally:
        client.close()


def test_hrana_execute_write_sends_typed_bound_arguments():
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        statements = [item.get("stmt", {}).get("sql") for item in body["requests"] if item["type"] == "execute"]
        results = [
            {"type": "ok", "response": {"type": "execute", "result": {"cols": [], "rows": []}}}
            for _ in statements
        ]
        if any(item["type"] == "close" for item in body["requests"]):
            results.append({"type": "ok", "response": {"type": "close"}})
            baton = None
        else:
            baton = "write-baton"
        return httpx.Response(200, json={"baton": baton, "results": results})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = HranaHttpClient("libsql://test-restore.turso.io", "test-token", http_client=http)
    try:
        transaction = client.transaction()
        transaction.execute_write(
            "INSERT INTO t VALUES (?, ?, ?, ?, ?)",
            (None, 7, 1.5, "hello", b"\\x00\\xff"),
        )
        statement = captured[1]["requests"][0]["stmt"]
        assert statement["sql"].startswith("INSERT")
        assert statement["args"] == [
            {"type": "null"},
            {"type": "integer", "value": "7"},
            {"type": "float", "value": 1.5},
            {"type": "text", "value": "hello"},
            {"type": "blob", "base64": "AP8="},
        ]
        transaction.rollback()
    finally:
        client.close()
