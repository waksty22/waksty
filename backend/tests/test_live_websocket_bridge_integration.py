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
    provider = None

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
        # A duplicate completion event must not replay writes after state reset.
        {"serverContent": {"turnComplete": True}},
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



def test_websocket_bridge_does_not_retry_or_duplicate_learning_after_storage_error(
    live_bridge, monkeypatch, caplog
):
    run, calls, _client = live_bridge
    observation_attempts = []

    def fail_observation(*_args, **_kwargs):
        observation_attempts.append("attempt")
        raise RuntimeError("simulated sensory storage failure")

    monkeypatch.setattr(server, "record_observation", fail_observation)
    run([
        {"serverContent": {"inputTranscription": {"text": "Bonjour"}}},
        {"serverContent": {"turnComplete": True}},
        # A later completion event must not retry the failed sensory write.
        {"serverContent": {"turnComplete": True}},
    ])

    assert observation_attempts == ["attempt"]
    assert calls["emotions"] == [("creator", "Bonjour")]
    assert len(calls["affective"]) == 1
    assert calls["links"] == []
    assert calls["learning"] == [("creator", "Bonjour")]
    assert calls["conversations"] == [
        ("creator", "Bonjour", "", {"source": "gemini_live"})
    ]
    assert "Échec mémorisation tour confirmé" in caplog.text



def test_websocket_bridge_executes_tool_calls_and_returns_matching_tool_response(
    live_bridge, monkeypatch
):
    run, _calls, _client = live_bridge
    executed = []

    def fake_execute_tool(name, args, user_id, **kwargs):
        executed.append((name, args, user_id, kwargs))
        return {"ok": True, "value": "fresh brain snapshot"}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    provider = run([
        {"serverContent": {"inputTranscription": {"text": "Que sais-tu de moi ?"}}},
        {"toolCall": {"functionCalls": [{
            "id": "call-17",
            "name": "get_shared_brain_state",
            "args": {},
        }]}},
        {"serverContent": {"outputTranscription": {"text": "Bonjour"}, "turnComplete": True}},
    ])

    assert executed == [(
        "get_shared_brain_state",
        {},
        "creator",
        {"user_source_text": "Que sais-tu de moi ?"},
    )]
    tool_response_messages = [
        message for message in provider.sent if "toolResponse" in message
    ]
    assert tool_response_messages == [{
        "toolResponse": {
            "functionResponses": [{
                "name": "get_shared_brain_state",
                "response": {"ok": True, "value": "fresh brain snapshot"},
                "id": "call-17",
            }]
        }
    }]


def test_websocket_bridge_provider_failure_preserves_partial_history_without_learning(
    live_bridge, monkeypatch
):
    _run, calls, client = live_bridge

    class FailingGeminiWebSocket:
        async def send(self, _payload):
            return None

        async def recv(self):
            return json.dumps({"setupComplete": {}})

        def __aiter__(self):
            async def iterate():
                try:
                    yield json.dumps({
                        "serverContent": {
                            "inputTranscription": {"text": "Je veux apprendre"}
                        }
                    })
                    raise RuntimeError("simulated provider stream failure")
                finally:
                    client.provider_finished.set()

            return iterate()

    @asynccontextmanager
    async def failing_provider_connection(_websocket):
        yield FailingGeminiWebSocket()

    monkeypatch.setattr(
        server, "supervised_gemini_connection", failing_provider_connection
    )

    async def execute():
        await server.websocket_endpoint(client, ticket="single-use-test-ticket")

    asyncio.run(execute())

    assert calls["emotions"] == []
    assert calls["affective"] == []
    assert calls["observations"] == []
    assert calls["links"] == []
    assert calls["learning"] == []
    assert calls["conversations"] == [(
        "creator",
        "Je veux apprendre",
        "",
        {"source": "gemini_live_interrupted"},
    )]



def test_websocket_bridge_keeps_concurrent_session_transcripts_isolated(
    live_bridge, monkeypatch
):
    _run, calls, client_a = live_bridge
    client_b = FakeClientWebSocket()
    provider_a = FakeGeminiWebSocket([
        {"serverContent": {"inputTranscription": {"text": "Session Alpha"}}},
        {"serverContent": {"turnComplete": True}},
    ], client_a)
    provider_b = FakeGeminiWebSocket([
        {"serverContent": {"inputTranscription": {"text": "Session Beta"}}},
        {"serverContent": {"turnComplete": True}},
    ], client_b)
    providers = {id(client_a): provider_a, id(client_b): provider_b}

    @asynccontextmanager
    async def concurrent_provider_connection(websocket):
        yield providers[id(websocket)]

    monkeypatch.setattr(
        server, "supervised_gemini_connection", concurrent_provider_connection
    )

    async def execute_both():
        await asyncio.gather(
            server.websocket_endpoint(client_a, ticket="ticket-alpha"),
            server.websocket_endpoint(client_b, ticket="ticket-beta"),
        )

    asyncio.run(execute_both())

    assert set(calls["emotions"]) == {
        ("creator", "Session Alpha"),
        ("creator", "Session Beta"),
    }
    assert set(calls["learning"]) == {
        ("creator", "Session Alpha"),
        ("creator", "Session Beta"),
    }
    assert {
        (user_text, source.get("source"))
        for _user, user_text, _assistant, source in calls["conversations"]
    } == {
        ("Session Alpha", "gemini_live"),
        ("Session Beta", "gemini_live"),
    }
    client_a_text = [
        item["text"] for item in client_a.sent if item.get("type") == "user_text"
    ]
    client_b_text = [
        item["text"] for item in client_b.sent if item.get("type") == "user_text"
    ]
    assert client_a_text == ["Session Alpha"]
    assert client_b_text == ["Session Beta"]
