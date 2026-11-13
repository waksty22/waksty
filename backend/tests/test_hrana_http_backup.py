import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.hrana_backup import HranaTransactionConnection
from storage.hrana_http import (
    HranaHttpClient,
    HranaHttpError,
    open_guarded_restore_transaction,
)
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
        self.base_url = None
        self.request_hosts = []

    def handle(self, request):
        self.request_hosts.append(request.url.host)
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
            elif sql.startswith("CREATE TRIGGER"):
                result = {"cols": [], "rows": []}
            elif "name = 'sqlite_sequence'" in sql:
                result = {"cols": [{"name": "1", "decltype": "INTEGER"}], "rows": []}
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
            elif "pragma_table_xinfo" in sql:
                result = {
                    "cols": [
                        {"name": "cid", "decltype": "INTEGER"},
                        {"name": "name", "decltype": "TEXT"},
                        {"name": "type", "decltype": "TEXT"},
                        {"name": "notnull", "decltype": "INTEGER"},
                        {"name": "dflt_value", "decltype": "TEXT"},
                        {"name": "pk", "decltype": "INTEGER"},
                        {"name": "hidden", "decltype": "INTEGER"},
                    ],
                    "rows": [
                        [_typed(0), _typed("id"), _typed("INTEGER"), _typed(0), _typed(None), _typed(0), _typed(0)],
                        [_typed(1), _typed("note"), _typed("TEXT"), _typed(0), _typed(None), _typed(0), _typed(0)],
                    ],
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
            json={"baton": self.baton, "base_url": self.base_url, "results": results},
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
        assert "pragma_table_xinfo" in server.statements[2]
        assert 'SELECT "id","note" FROM "memories"' == server.statements[3]
        assert server.statements[5] == "COMMIT"
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

def test_http_v2_write_allows_trigger_body_semicolons_but_rejects_extra_statements():
    server = FakeHranaServer()
    client = _client(server)
    transaction = None
    trigger_sql = (
        "CREATE TRIGGER memories_after_insert AFTER INSERT ON memories "
        "BEGIN INSERT INTO memories(id, note) VALUES (NEW.id + 1000, NEW.note); END;"
    )
    try:
        transaction = client.transaction()
        result = transaction.execute_write(trigger_sql)
        assert result.columns == ()
        assert server.statements == ["BEGIN", trigger_sql]
        with pytest.raises(PermissionError):
            transaction.execute_write(trigger_sql + " DROP TABLE memories;")
        with pytest.raises(PermissionError):
            transaction.execute_write("/* harmless prefix */ COMMIT")
        assert server.statements == ["BEGIN", trigger_sql]
        transaction.rollback()
    finally:
        client.close()


def test_single_statement_guard_accepts_trailing_comments_and_quoted_semicolons():
    from storage.hrana_http import _is_single_sql_statement
    assert _is_single_sql_statement("SELECT ';' /* trailing comment */")
    assert _is_single_sql_statement("CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END;")
    assert not _is_single_sql_statement("SELECT 1; SELECT 2")
    assert not _is_single_sql_statement("SELECT 1; -- comment\nDROP TABLE t")



def test_guarded_restore_checks_exact_host_before_opening_transaction():
    server = FakeHranaServer()
    http = httpx.Client(transport=httpx.MockTransport(server.handle))
    try:
        with pytest.raises(PermissionError):
            open_guarded_restore_transaction(
                "libsql://isolated-db.turso.io",
                "test-token",
                expected_target_identity="different-db.turso.io",
                production_identity="chappie-db.turso.io",
                http_client=http,
            )
        with pytest.raises(PermissionError):
            open_guarded_restore_transaction(
                "libsql://chappie-db.turso.io",
                "test-token",
                expected_target_identity="chappie-db.turso.io",
                production_identity="chappie-db.turso.io",
                http_client=http,
            )
        assert server.statements == []
        assert server.active is False
    finally:
        http.close()


def test_guarded_restore_opens_transaction_only_for_expected_nonproduction_host():
    server = FakeHranaServer()
    http = httpx.Client(transport=httpx.MockTransport(server.handle))
    client = transaction = None
    try:
        client, transaction = open_guarded_restore_transaction(
            "libsql://isolated-db.turso.io",
            "test-token",
            expected_target_identity="ISOLATED-DB.TURSO.IO",
            production_identity="chappie-db.turso.io",
            http_client=http,
        )
        assert server.statements == ["BEGIN"]
        assert server.active is True
        transaction.rollback()
        assert server.statements == ["BEGIN", "ROLLBACK"]
        assert server.active is False
    finally:
        if transaction is not None and transaction._active:
            transaction.rollback()
        if client is not None:
            client.close()
        http.close()


def test_http_rejects_cross_origin_base_url_without_forwarding_auth_token():
    server = FakeHranaServer()
    server.base_url = "https://attacker.example/v2/pipeline"
    client = _client(server)
    try:
        with pytest.raises(HranaHttpError, match="origine de connexion"):
            client.transaction()
        assert client._endpoint == "https://example-org.turso.io/v2/pipeline"
        assert server.request_hosts == ["example-org.turso.io"]
    finally:
        client.close()


def test_http_accepts_same_origin_base_url_update_and_keeps_stream_working():
    server = FakeHranaServer()
    server.base_url = "https://EXAMPLE-ORG.TURSO.IO"
    client = _client(server)
    transaction = None
    try:
        transaction = client.transaction()
        assert client._endpoint == "https://example-org.turso.io/v2/pipeline"
        transaction.rollback()
        assert server.request_hosts == ["example-org.turso.io", "example-org.turso.io"]
        assert server.closed is True
        assert server.active is False
    finally:
        if transaction is not None and transaction._active:
            transaction.rollback()
        client.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example-org.turso.io.attacker.example",
        "https://example-org.turso.io:444",
        "http://example-org.turso.io",
    ],
)
def test_http_rejects_deceptive_or_downgraded_base_url_updates(base_url):
    server = FakeHranaServer()
    server.base_url = base_url
    client = _client(server)
    try:
        with pytest.raises(HranaHttpError, match="origine de connexion"):
            client.transaction()
        assert server.request_hosts == ["example-org.turso.io"]
        assert client._endpoint == "https://example-org.turso.io/v2/pipeline"
    finally:
        client.close()
