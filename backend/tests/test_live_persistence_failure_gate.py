"""A Live turn must not be acknowledged when durable learning writes fail."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager


class FakeClientWebSocket:
    def __init__(self):
        self.payloads = [{"action": "audio_chunk", "pcm_data": "AQID"}]
        self.sent = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if self.payloads:
            return self.payloads.pop(0)
        await asyncio.Future()

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class FakeGeminiLiveSocket:
    def __init__(self):
        self.sent = []
        self.ready = asyncio.Event()
        self.yielded = False

    async def send(self, raw):
        payload = json.loads(raw)
        self.sent.append(payload)
        if isinstance(payload.get("realtimeInput"), dict):
            self.ready.set()

    async def recv(self):
        return json.dumps({"setupComplete": {}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.yielded:
            raise StopAsyncIteration
        await asyncio.wait_for(self.ready.wait(), timeout=5)
        self.yielded = True
        return json.dumps({
            "serverContent": {
                "inputTranscription": {"text": "Bonjour"},
                "outputTranscription": {"text": "Salut"},
                "modelTurn": {"parts": [{"text": "Salut"}]},
                "turnComplete": True,
            }
        })


def test_live_learning_write_failure_never_emits_turn_complete(
    monkeypatch, tmp_path
):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "live-write-failure.sqlite3")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-provider-key")
    server.init_db()

    def fail_learning(*args, **kwargs):
        raise RuntimeError("simulated learning persistence failure")

    monkeypatch.setattr(server, "record_confirmed_turn_learning", fail_learning)
    provider = FakeGeminiLiveSocket()

    @asynccontextmanager
    async def fake_connection(websocket):
        yield provider

    monkeypatch.setattr(server, "supervised_gemini_connection", fake_connection)
    client = FakeClientWebSocket()
    ticket = server.live_ws_tickets.issue("creator")

    asyncio.run(server.websocket_endpoint(client, ticket=ticket))

    assert client.accepted
    assert client.closed
    assert not any(item.get("type") == "turn_complete" for item in client.sent)
    assert any(item.get("type") == "error" for item in client.sent)

    with server.db_connection() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE user_id=? AND content='Bonjour'",
            ("creator",),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM journal "
            "WHERE user_id=? AND kind='gemini_live_interrupted'",
            ("creator",),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM personal_vocabulary WHERE user_id=?",
            ("creator",),
        ).fetchone()[0] == 0
