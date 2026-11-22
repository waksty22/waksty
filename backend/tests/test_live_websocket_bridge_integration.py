"""End-to-end tests for the Gemini Live WebSocket bridge using fake sockets.

No Gemini credentials, network connection, or production database are used.
"""

from contextlib import asynccontextmanager, contextmanager
import asyncio
import json
from pathlib import Path
import sys

import pytest
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


class FakeClientWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = []
        self.provider_finished = asyncio.Event()

    async def accept(self):
        return None

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=None):
        self.closed.append((code, reason))

    async def receive_json(self):
        await self.provider_finished.wait()
        raise WebSocketDisconnect(code=1000)


class FakeGeminiWebSocket:
    def __init__(self, responses, client):
        self.responses = list(responses)
        self.client = client
        self.sent = []
        self._setup_read = False

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        if self._setup_read:
            raise AssertionError("Unexpected extra setup receive")
        self._setup_read = True
        return json.dumps({"setupComplete": {}})

    def __aiter__(self):
        async def iterate():
            try:
                for response in self.responses:
                    yield json.dumps(response)
            finally:
                self.client.provider_finished.set()

        return iterate()


class DummyDB:
    def commit(self):
        return None


@pytest.fixture
def live_bridge(monkeypatch):
    client = FakeClientWebSocket()
    calls = {
        "emotions": [],
        "affective": [],
        "observations": [],
        "links": [],
        "learning": [],
        "conversations": [],
    }
    db = DummyDB()

    @contextmanager
    def fake_db_connection():
        yield db

    @asynccontextmanager
    async def fake_provider_connection(_websocket):
        yield provider

    async def finish_initialization(task, _websocket):
        return await task

    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(server.live_ws_tickets, "consume", lambda _ticket: "creator")
    monkeypatch.setattr(server, "valid_user", lambda value: value)
    monkeypatch.setattr(server, "get_identity_prompt", lambda _user: "identity")
    monkeypatch.setattr(server, "build_untrusted_identity_context_message", lambda _user: {"role": "user", "parts": [{"text": "identity"}]})
    monkeypatch.setattr(server, "build_live_initial_history", lambda *_args: {"role": "user", "parts": [{"text": "seed"}]})
    monkeypatch.setattr(server, "db_connection", fake_db_connection)
    monkeypatch.setattr(server, "get_repeatable_words", lambda _db, _user: ["bonjour"])
    monkeypatch.setattr(server, "get_skills_summary", lambda _user: {"average_level": 0})
    monkeypatch.setattr(server, "text_uses_only_allowed_words", lambda *_args: True)
    monkeypatch.setattr(server, "update_emotions_once", lambda user, text: calls["emotions"].append((user, text)) or {"joy": 50})
    monkeypatch.setattr(server, "record_affective_snapshot", lambda _db, user, state, **kw: calls["affective"].append((user, state, kw)))
    monkeypatch.setattr(server, "record_observation", lambda _db, user, modality, text, source, **kw: calls["observations"].append((user, modality, text, source, kw)) or {"observation_id": "obs-1"})
    monkeypatch.setattr(server, "link_temporally_cooccurring_observation", lambda _db, user, observation_id: calls["links"].append((user, observation_id)))
    monkeypatch.setattr(server, "record_confirmed_turn_learning", lambda _db, user, text: calls["learning"].append((user, text)) or {"heard": [], "taught": []})
    monkeypatch.setattr(server, "save_conversation_turn", lambda user, user_text, assistant_text, **kw: calls["conversations"].append((user, user_text, assistant_text, kw)))
    monkeypatch.setattr(server, "supervise_live_initialization", finish_initialization)

    def run(responses):
        nonlocal provider
        provider = FakeGeminiWebSocket(responses, client)

        async def execute():
            await server.websocket_endpoint(client, ticket="single-use-test-ticket")

        asyncio.run(execute())
        return provider

    monkeypatch.setattr(server, "supervised_gemini_connection", fake_provider_connection)
    return run, calls, client


def test_websocket_bridge_commits_cognitive_learning_once_after_merged_turn(live_bridge):
    run, calls, client = live_bridge
    provider = run([
        {"serverContent": {"inputTranscription": {"text": "Bonjour tout"}}},
        {"serverContent": {"inputTranscription": {"text": "tout le monde"}}},
        {"serverContent": {"outputTranscription": {"text": "Bonjour"}, "turnComplete": True}},
    ])

    assert calls["emotions"] == [("creator", "Bonjour tout le monde")]
    assert len(calls["affective"]) == 1
    assert calls["observations"] == [
        ("creator", "audio", "Bonjour tout le monde", "gemini_live_transcription", {"confidence": 0.8, "metadata": {"language": "fr"}})
    ]
    assert calls["links"] == [("creator", "obs-1")]
    assert calls["learning"] == [("creator", "Bonjour tout le monde")]
    assert calls["conversations"] == [
        ("creator", "Bonjour tout le monde", "Bonjour", {"source": "gemini_live"})
    ]
    relayed_text = [item["text"] for item in client.sent if item.get("type") == "user_text"]
    assert relayed_text == ["Bonjour tout", "le monde"]
    assert any(item.get("type") == "turn_complete" for item in client.sent)
    assert provider.sent[0]["setup"]["tools"] == server.TOOLS


def test_websocket_bridge_never_promotes_disconnected_partial_transcript(live_bridge):
    run, calls, _client = live_bridge
    run([
        {"serverContent": {"inputTranscription": {"text": "Je voudrais apprendre"}}},
        {"serverContent": {"inputTranscription": {"text": "le mot bonjour"}}},
    ])

    assert calls["emotions"] == []
    assert calls["affective"] == []
    assert calls["observations"] == []
    assert calls["links"] == []
    assert calls["learning"] == []
    assert calls["conversations"] == [
        ("creator", "Je voudrais apprendre le mot bonjour", "", {"source": "gemini_live_interrupted"})
    ]
