"""End-to-end proof that newborn Live speech never emits unknown vocabulary."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager


class FakeClientWebSocket:
    def __init__(self):
        self.payloads = [{"action": "audio_chunk", "pcm_data": "AQID"}]
        self.sent: list[dict] = []
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
    def __init__(self, assistant_text: str):
        self.assistant_text = assistant_text
        self.sent: list[dict] = []
        self.ready = asyncio.Event()
        self.yielded = False

    async def send(self, raw: str):
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
                "inputTranscription": {"text": "bonjour"},
                "outputTranscription": {"text": self.assistant_text},
                "modelTurn": {
                    "parts": [
                        {"text": self.assistant_text},
                        {
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": "AQID",
                            }
                        },
                    ]
                },
                "turnComplete": True,
            }
        })


def run_live_turn(monkeypatch, tmp_path, assistant_text: str):
    import server
    from learning.language import record_heard_word

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "newborn-live-gate.sqlite3")
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-provider-key")
    server.init_db()

    # The only word Chappie has previously encountered is "bonjour".
    with server.db_connection() as db:
        record_heard_word(db, "creator", "bonjour", "Exposition de test")
        db.commit()

    provider = FakeGeminiLiveSocket(assistant_text)

    @asynccontextmanager
    async def fake_connection(websocket):
        yield provider

    monkeypatch.setattr(server, "supervised_gemini_connection", fake_connection)
    client = FakeClientWebSocket()
    ticket = server.live_ws_tickets.issue("creator")
    asyncio.run(server.websocket_endpoint(client, ticket=ticket))
    return client.sent


def test_live_blocks_audio_and_text_when_transcript_contains_unknown_word(
    monkeypatch, tmp_path
):
    messages = run_live_turn(monkeypatch, tmp_path, "bonjour inconnu")

    assert any(item.get("type") == "speech_blocked" for item in messages)
    assert not any(item.get("type") == "audio_stream" for item in messages)
    assert not any(item.get("type") == "text" for item in messages)


def test_live_emits_audio_only_when_every_spoken_word_is_known(
    monkeypatch, tmp_path
):
    messages = run_live_turn(monkeypatch, tmp_path, "bonjour")

    assert any(item.get("type") == "audio_stream" for item in messages)
    assert any(
        item.get("type") == "text" and item.get("text") == "bonjour"
        for item in messages
    )
    assert not any(item.get("type") == "speech_blocked" for item in messages)
