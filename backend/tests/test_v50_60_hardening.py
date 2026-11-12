import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from utils.live_tickets import OneTimeTicketStore

def test_request_body_limit_rejects_chunked_body_without_content_length():
    import server

    app_called = False

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": bytes(body)})

    messages = [
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    middleware = server.RequestBodyLimitMiddleware(app, max_bytes=6)
    asyncio.run(middleware(
        {"type": "http", "method": "POST", "path": "/api/test", "headers": []},
        receive,
        send,
    ))

    assert app_called is False
    assert sent[0]["status"] == 413


def test_request_body_limit_replays_valid_chunked_body():
    import server

    async def app(scope, receive, send):
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": bytes(body)})

    messages = [
        {"type": "http.request", "body": b"12", "more_body": True},
        {"type": "http.request", "body": b"34", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    middleware = server.RequestBodyLimitMiddleware(app, max_bytes=6)
    asyncio.run(middleware(
        {"type": "http", "method": "POST", "path": "/api/test", "headers": []},
        receive,
        send,
    ))

    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b"1234"


def test_request_body_limit_rejects_oversized_content_length():
    import server

    async def app(scope, receive, send):
        pytest.fail("The downstream app must not run for an oversized request.")

    async def receive():
        pytest.fail("The request body must not be read after an oversized header.")

    sent = []

    async def send(message):
        sent.append(message)

    middleware = server.RequestBodyLimitMiddleware(app, max_bytes=6)
    asyncio.run(middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [(b"content-length", b"7")],
        },
        receive,
        send,
    ))

    assert sent[0]["status"] == 413


def test_reset_requires_server_side_confirmation_and_only_targets_active_backend(
    monkeypatch,
):
    import server

    monkeypatch.setattr(server, "_authenticated_user", lambda auth: "creator")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(
        server,
        "reset_chappie_life",
        lambda user_id: {"reset": True, "user_id": user_id},
    )
    monkeypatch.setattr(
        server,
        "reset_turso_life",
        lambda user_id: pytest.fail("The inactive Turso database must not be touched."),
    )

    payload = server.ResetRequest(confirmation="REINITIALISER CHAPPIE")
    result = asyncio.run(server.api_reset(payload, auth="creator"))

    assert result["success"] is True
    assert result["database_reset"] == "sqlite"
    assert result["inactive_database_untouched"] is True


def test_reset_is_blocked_during_storage_cutover(monkeypatch):
    import server

    monkeypatch.setattr(server, "_authenticated_user", lambda auth: "creator")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", True)
    monkeypatch.setattr(
        server,
        "reset_chappie_life",
        lambda user_id: pytest.fail("Reset must be blocked during cutover."),
    )

    payload = server.ResetRequest(confirmation="REINITIALISER CHAPPIE")
    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(server.api_reset(payload, auth="creator"))

    assert exc.value.status_code == 409


def test_interrupted_live_turn_is_saved_as_partial_and_state_is_cleared(monkeypatch):
    import server

    saved = []
    monkeypatch.setattr(
        server,
        "save_conversation_turn",
        lambda user, user_text, assistant_text, source: saved.append(
            (user, user_text, assistant_text, source)
        ),
    )
    state = {
        "user": "Bonjour Chappie",
        "assistant": "Bonjour, je",
        "audio": [{"audio": "discarded"}],
    }

    assert server.persist_interrupted_live_turn("creator", state) is True
    assert saved == [(
        "creator",
        "Bonjour Chappie",
        "Bonjour, je",
        "gemini_live_interrupted",
    )]
    assert state == {"user": "", "assistant": "", "audio": []}


def test_empty_interrupted_live_turn_does_not_write(monkeypatch):
    import server

    monkeypatch.setattr(
        server,
        "save_conversation_turn",
        lambda *args, **kwargs: pytest.fail("An empty turn must not be saved."),
    )
    state = {"user": "", "assistant": "", "audio": []}

    assert server.persist_interrupted_live_turn("creator", state) is False


def test_cutover_middleware_blocks_writes_and_allows_readonly_diagnostics(
    monkeypatch,
):
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import server

    monkeypatch.setattr(
        server,
        "STORAGE_MIGRATION_PENDING_CUTOVER",
        True,
    )

    async def readonly_probe(request):
        return JSONResponse({"probe": "middleware_passed"})

    original_routes = server.app.router.routes
    monkeypatch.setattr(
        server.app.router,
        "routes",
        [
            Route(
                "/api/system/diagnostics",
                readonly_probe,
                methods=["GET"],
            ),
            *original_routes,
        ],
    )

    client = TestClient(server.app)

    blocked = client.post(
        "/api/cutover-write-guard-probe",
        json={"probe": True},
    )
    assert blocked.status_code == 503
    assert blocked.json().get("detail")

    diagnostic = client.get("/api/system/diagnostics")
    assert diagnostic.status_code == 200, diagnostic.text
    assert diagnostic.json() == {"probe": "middleware_passed"}

def test_live_websocket_rejects_cutover_without_consuming_ticket(monkeypatch):
    import server
    store = OneTimeTicketStore(token_factory=lambda: "cutover-ticket")
    ticket = store.issue("creator")

    monkeypatch.setattr(server, "live_ws_tickets", store)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", True)

    client = TestClient(server.app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/live?ticket={ticket}"):
            pytest.fail("Le WebSocket ne doit pas accepter la connexion pendant le cutover.")

    assert exc.value.code == 1013
    assert store.consume(ticket) == "creator"


def test_live_bridge_supervisor_cancels_blocked_tasks_on_cutover(monkeypatch):
    import server

    class FakeWebSocket:
        def __init__(self):
            self.close_calls = []

        async def close(self, code, reason):
            self.close_calls.append((code, reason))

    async def scenario():
        monkeypatch.setattr(
            server,
            "STORAGE_MIGRATION_PENDING_CUTOVER",
            False,
        )

        websocket = FakeWebSocket()
        started = asyncio.Event()
        cancelled = []

        async def blocked_bridge(name):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

        client_task = asyncio.create_task(blocked_bridge("client"))
        gemini_task = asyncio.create_task(blocked_bridge("gemini"))

        await started.wait()
        await asyncio.sleep(0)

        supervisor = asyncio.create_task(
            server.supervise_live_bridge_tasks(
                client_task,
                gemini_task,
                websocket,
            )
        )

        await asyncio.sleep(0.02)
        server.STORAGE_MIGRATION_PENDING_CUTOVER = True

        await asyncio.wait_for(supervisor, timeout=2)

        assert client_task.done()
        assert gemini_task.done()
        assert sorted(cancelled) == ["client", "gemini"]
        assert len(websocket.close_calls) == 1
        assert websocket.close_calls[0][0] == 1013

    asyncio.run(scenario())


def test_live_bridge_supervisor_handles_normal_task_completion(monkeypatch):
    import server

    class FakeWebSocket:
        def __init__(self):
            self.close_calls = []

        async def close(self, code, reason):
            self.close_calls.append((code, reason))

    async def scenario():
        monkeypatch.setattr(
            server,
            "STORAGE_MIGRATION_PENDING_CUTOVER",
            False,
        )

        websocket = FakeWebSocket()
        cancelled = []

        async def completed_bridge():
            return "completed"

        async def blocked_bridge():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        client_task = asyncio.create_task(completed_bridge())
        gemini_task = asyncio.create_task(blocked_bridge())

        await asyncio.sleep(0)

        await asyncio.wait_for(
            server.supervise_live_bridge_tasks(
                client_task,
                gemini_task,
                websocket,
            ),
            timeout=2,
        )

        assert client_task.done()
        assert not client_task.cancelled()
        assert gemini_task.done()
        assert gemini_task.cancelled()
        assert cancelled == [True]
        assert websocket.close_calls == []

    asyncio.run(scenario())

def test_live_initialization_supervisor_cancels_blocked_operation_on_cutover(monkeypatch):
    import server

    class FakeWebSocket:
        def __init__(self):
            self.close_calls = []

        async def close(self, code, reason):
            self.close_calls.append((code, reason))

    async def scenario():
        monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
        websocket = FakeWebSocket()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_operation():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        operation = asyncio.create_task(blocked_operation())
        await started.wait()

        supervisor = asyncio.create_task(
            server.supervise_live_initialization(operation, websocket)
        )
        await asyncio.sleep(0.02)
        server.STORAGE_MIGRATION_PENDING_CUTOVER = True

        with pytest.raises(server.LiveStorageCutover):
            await asyncio.wait_for(supervisor, timeout=2)

        assert operation.done()
        assert cancelled.is_set()
        assert websocket.close_calls == [
            (1013, "Migration memoire en cours de bascule vers Turso.")
        ]

    asyncio.run(scenario())

def test_supervised_gemini_connection_closes_manager_after_normal_session(monkeypatch):
    import server

    class FakeManager:
        def __init__(self):
            self.enter_calls = 0
            self.exit_calls = 0
            self.connection = object()

        async def __aenter__(self):
            self.enter_calls += 1
            return self.connection

        async def __aexit__(self, exc_type, exc, tb):
            self.exit_calls += 1

    async def scenario():
        monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
        manager = FakeManager()

        with patch.object(server.websockets, "connect", return_value=manager):
            class FakeWebSocket:
                async def close(self, code, reason):
                    raise AssertionError("La fermeture client ne doit pas être appelée.")

            async with server.supervised_gemini_connection(FakeWebSocket()) as connection:
                assert connection is manager.connection
                assert manager.enter_calls == 1
                assert manager.exit_calls == 0

            assert manager.exit_calls == 1

    asyncio.run(scenario())

def test_supervised_gemini_connection_propagates_open_failure_without_exit(monkeypatch):
    import server

    class FakeManager:
        def __init__(self):
            self.exit_calls = 0

        async def __aenter__(self):
            raise OSError("Gemini Live connection failed")

        async def __aexit__(self, exc_type, exc, tb):
            self.exit_calls += 1

    class FakeWebSocket:
        async def close(self, code, reason):
            raise AssertionError("Aucune fermeture client ne doit ?tre appel?e.")

    async def scenario():
        monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
        manager = FakeManager()

        with patch.object(server.websockets, "connect", return_value=manager):
            with pytest.raises(OSError, match="Gemini Live connection failed"):
                async with server.supervised_gemini_connection(FakeWebSocket()):
                    pytest.fail("La connexion ne doit pas ?tre ?tablie.")

        assert manager.exit_calls == 0

    asyncio.run(scenario())


def test_supervised_gemini_connection_cancels_blocked_open_on_cutover(monkeypatch):
    import server

    class FakeManager:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.exit_calls = 0

        async def __aenter__(self):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

        async def __aexit__(self, exc_type, exc, tb):
            self.exit_calls += 1

    class FakeWebSocket:
        def __init__(self):
            self.close_calls = []

        async def close(self, code, reason):
            self.close_calls.append((code, reason))

    async def scenario():
        monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
        manager = FakeManager()
        websocket = FakeWebSocket()

        with patch.object(server.websockets, "connect", return_value=manager):
            async def use_connection():
                async with server.supervised_gemini_connection(websocket):
                    pytest.fail("La connexion ne doit pas être établie.")

            task = asyncio.create_task(use_connection())
            await asyncio.wait_for(manager.started.wait(), timeout=2)

            server.STORAGE_MIGRATION_PENDING_CUTOVER = True

            with pytest.raises(server.LiveStorageCutover):
                await asyncio.wait_for(task, timeout=2)

        assert manager.cancelled.is_set()
        assert manager.exit_calls == 0
        assert websocket.close_calls == [
            (1013, "Migration memoire en cours de bascule vers Turso.")
        ]

    asyncio.run(scenario())

def test_live_initialization_supervisor_cancels_operation_on_external_cancellation(
    monkeypatch,
):
    import server

    async def scenario():
        monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_operation():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        operation = asyncio.create_task(blocked_operation())
        await started.wait()

        supervisor = asyncio.create_task(
            server.supervise_live_initialization(operation, object())
        )
        await asyncio.sleep(0)

        supervisor.cancel()

        with pytest.raises(asyncio.CancelledError):
            await supervisor

        was_cancelled = cancelled.is_set()

        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)

        assert was_cancelled, (
            "L'annulation du superviseur doit aussi annuler l'opération enfant."
        )

    asyncio.run(scenario())


def test_remote_migration_marker_absent_is_valid_pre_migration_state(monkeypatch):
    import types
    import server

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def execute(self, query, params=None):
            if "sqlite_master" in query:
                return Cursor(None)
            raise AssertionError(f"Unexpected query: {query}")

        def close(self):
            pass

    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setitem(
        sys.modules,
        "libsql",
        types.SimpleNamespace(connect=lambda **kwargs: Connection()),
    )

    assert server._remote_turso_migration_completed(allow_missing_marker=True) is False


def test_missing_sqlite_checks_remote_migration_marker_even_when_gate_disabled(
    monkeypatch, tmp_path
):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "missing.sqlite3")
    monkeypatch.setattr(server, "_local_migration_pending_cutover", lambda: False)
    monkeypatch.setattr(server, "_remote_turso_migration_completed", lambda **kwargs: True)
    monkeypatch.setattr(
        server,
        "db_connection",
        lambda: pytest.fail("A new empty SQLite database must not be created."),
    )
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    server.init_db()

    assert server.STORAGE_MIGRATION_PENDING_CUTOVER is True



def test_migration_cancel_keeps_local_gate_when_remote_marker_delete_fails(
    monkeypatch, tmp_path
):
    import types
    import server

    events = []

    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class LocalConnection:
        def execute(self, query, params=None):
            events.append(("local_execute", query.strip().split()[0].upper()))
            if "SELECT 1 FROM sqlite_master" in query:
                return Cursor((1,))
            if "SELECT status FROM chappie_storage_migration_state" in query:
                return Cursor(("pending_cutover",))
            return Cursor()

        def commit(self):
            events.append(("local_commit", None))

        def rollback(self):
            events.append(("local_rollback", None))

        def close(self):
            events.append(("local_close", None))

    class RemoteConnection:
        def execute(self, query, params=None):
            events.append(("remote_delete_attempt", None))
            raise OSError("simulated Turso outage")

        def commit(self):
            events.append(("remote_commit", None))

        def close(self):
            events.append(("remote_close", None))

    local = LocalConnection()
    monkeypatch.setattr(server, "_authenticated_user", lambda auth: "creator")
    monkeypatch.setattr(server.StorageSettings, "from_env", classmethod(
        lambda cls: cls(backend="sqlite")
    ))
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "source.sqlite3")
    server.DB_PATH.touch()
    monkeypatch.setattr(server.sqlite3, "connect", lambda *args, **kwargs: local)
    monkeypatch.setenv("CHAPPIE_ALLOW_SQLITE_ROLLBACK", "1")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", True)
    monkeypatch.setitem(
        sys.modules,
        "libsql",
        types.SimpleNamespace(
            connect=lambda **kwargs: RemoteConnection()
        ),
    )

    payload = server.TursoMigrationCancelRequest(
        confirmation="ANNULER LA BASCULE TURSO"
    )
    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(server.api_storage_migration_cancel(payload, auth="creator"))

    assert exc.value.status_code == 503
    assert ("remote_delete_attempt", None) in events
    assert ("local_rollback", None) in events
    assert ("local_commit", None) not in events
    assert not any(
        event[0] == "local_execute" and event[1] in {"DROP", "UPDATE"}
        for event in events
    )
    assert server.STORAGE_MIGRATION_PENDING_CUTOVER is True
