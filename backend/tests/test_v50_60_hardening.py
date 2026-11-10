import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


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
