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
        self.incoming_payloads = []
        self.incoming_index = 0
        self.coordinate_refresh = False
        self.next_input_event = asyncio.Event()
        self.second_input_received = asyncio.Event()

    async def accept(self):
        return None

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=None):
        self.closed.append((code, reason))

    async def receive_json(self):
        if self.incoming_index < len(self.incoming_payloads):
            index = self.incoming_index
            if index == 1 and self.coordinate_refresh:
                await self.next_input_event.wait()
            payload = self.incoming_payloads[index]
            self.incoming_index += 1
            if index == 1 and self.coordinate_refresh:
                self.second_input_received.set()
            return payload
        await self.provider_finished.wait()
        raise WebSocketDisconnect(code=1000)


class FakeGeminiWebSocket:
    def __init__(self, responses, client):
        self.responses = list(responses)
        self.client = client
        self.sent = []
        self._setup_read = False
        self.refresh_count = 0

    async def send(self, payload):
        message = json.loads(payload)
        is_refresh = message.get("clientContent", {}).get("turnComplete") is False
        if is_refresh:
            self.refresh_count += 1
        if (
            self.client.coordinate_refresh
            and is_refresh
            and self.refresh_count >= 2
        ):
            self.client.next_input_event.set()
            await self.client.second_input_received.wait()
            # Let the client task reach the provider-send gate while the brain
            # refresh is still in flight.
            await asyncio.sleep(0)
        self.sent.append(message)

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
    monkeypatch.setattr(
        server,
        "get_shared_brain_snapshot",
        lambda _db, _user, limit=8, query=None: {
            "snapshot_version": "34.0",
            "statistics": {"totals": {}},
            "vocabulary": [{"word": "bonjour", "state": "usable"}],
        },
    )
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
    assert not any(
        message.get("clientContent", {}).get("turnComplete") is False
        for message in provider.sent
    ), "Unchanged brain snapshots should not be resent."


def test_websocket_bridge_records_memory_doubt_only_after_turn_persistence(
    live_bridge, monkeypatch
):
    run, _calls, _client = live_bridge
    events = []

    def record_turn(user, user_text, assistant_text, **kwargs):
        events.append(("persist", user, user_text, assistant_text, kwargs))

    def record_doubt(user, query, *, channel, relevant_memories=None):
        events.append(("doubt", user, query, channel))

    monkeypatch.setattr(server, "save_conversation_turn", record_turn)
    monkeypatch.setattr(server, "record_memory_relevance_doubt_trace", record_doubt)

    run([
        {"serverContent": {"inputTranscription": {"text": "Bonjour"}}},
        {"serverContent": {"outputTranscription": {"text": "Bonjour"}, "turnComplete": True}},
    ])

    assert [event[0] for event in events] == ["persist", "doubt"]
    assert events[0][1:] == (
        "creator", "Bonjour", "Bonjour", {"source": "gemini_live"}
    )
    assert events[1] == ("doubt", "creator", "Bonjour", "gemini_live")


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



def test_websocket_bridge_discards_interrupted_model_output_before_final_turn(
    live_bridge, monkeypatch,
):
    run, calls, client = live_bridge
    # This test targets interruption semantics, not the separate maturity gate.
    monkeypatch.setattr(server, "get_skills_summary", lambda _user: {"average_level": 3})
    provider = run([
        {"serverContent": {
            "inputTranscription": {"text": "Explique-moi"},
            "outputTranscription": {"text": "Réponse interrompue"},
            "modelTurn": {"parts": [{
                "inlineData": {
                    "data": "cGFydGlhbA==",
                    "mimeType": "audio/pcm;rate=24000",
                }
            }]},
        }},
        {"serverContent": {"interrupted": True}},
        {"serverContent": {
            "outputTranscription": {"text": "Réponse finale"},
            "modelTurn": {"parts": [{
                "inlineData": {
                    "data": "ZmluYWw=",
                    "mimeType": "audio/pcm;rate=24000",
                }
            }]},
            "turnComplete": True,
        }},
    ])

    assert calls["conversations"] == [
        ("creator", "Explique-moi", "Réponse finale", {"source": "gemini_live"})
    ]
    audio_streams = [
        item for item in client.sent if item.get("type") == "audio_stream"
    ]
    assert audio_streams == [{
        "type": "audio_stream",
        "audio": "ZmluYWw=",
        "sample_rate": 24000,
    }]
    assert any(item.get("type") == "interrupt" for item in client.sent)
    assert calls["learning"] == [("creator", "Explique-moi")]
    assert provider.sent[0]["setup"]["model"] == f"models/{server.GEMINI_LIVE_MODEL}"


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
    assert calls["learning"] == []
    assert calls["conversations"] == [
        ("creator", "Bonjour", "", {"source": "gemini_live_interrupted"})
    ]
    assert "simulated sensory storage failure" in caplog.text



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


def test_websocket_bridge_reconnect_starts_with_fresh_turn_state(live_bridge, monkeypatch):
    _run, calls, first_client = live_bridge
    second_client = FakeClientWebSocket()

    class InterruptedProvider:
        async def send(self, _payload):
            return None

        async def recv(self):
            return json.dumps({"setupComplete": {}})

        def __aiter__(self):
            async def iterate():
                try:
                    yield json.dumps({
                        "serverContent": {
                            "inputTranscription": {"text": "Ancien tour incomplet"}
                        }
                    })
                    raise RuntimeError("simulated connection loss")
                finally:
                    first_client.provider_finished.set()

            return iterate()

    second_provider = FakeGeminiWebSocket([
        {"serverContent": {"inputTranscription": {"text": "Nouveau tour propre"}}},
        {"serverContent": {"turnComplete": True}},
    ], second_client)
    providers = {
        id(first_client): InterruptedProvider(),
        id(second_client): second_provider,
    }

    @asynccontextmanager
    async def reconnecting_provider_connection(websocket):
        yield providers[id(websocket)]

    monkeypatch.setattr(
        server, "supervised_gemini_connection", reconnecting_provider_connection
    )

    async def execute_reconnect():
        await server.websocket_endpoint(first_client, ticket="first-ticket")
        await server.websocket_endpoint(second_client, ticket="second-ticket")

    asyncio.run(execute_reconnect())

    assert calls["learning"] == [("creator", "Nouveau tour propre")]
    assert calls["emotions"] == [("creator", "Nouveau tour propre")]
    assert {
        (user_text, source.get("source"))
        for _user, user_text, _assistant, source in calls["conversations"]
    } == {
        ("Ancien tour incomplet", "gemini_live_interrupted"),
        ("Nouveau tour propre", "gemini_live"),
    }


@pytest.mark.parametrize("malformed_completion", ["false", 1, {"complete": True}])
def test_websocket_bridge_rejects_non_boolean_turn_complete_flags(
    live_bridge, malformed_completion
):
    run, calls, _client = live_bridge
    run([
        {"serverContent": {"inputTranscription": {"text": "Apprentissage partiel"}}},
        {"serverContent": {"turnComplete": malformed_completion}},
    ])

    assert calls["emotions"] == []
    assert calls["affective"] == []
    assert calls["observations"] == []
    assert calls["links"] == []
    assert calls["learning"] == []
    assert calls["conversations"] == [(
        "creator",
        "Apprentissage partiel",
        "",
        {"source": "gemini_live_interrupted"},
    )]


def test_websocket_bridge_refreshes_audio_memory_before_forwarding_pcm(
    live_bridge, monkeypatch
):
    run, calls, client = live_bridge
    client.incoming_payloads = [
        {"action": "audio_transcript_ready", "text": "Parle-moi du chien"},
        {"action": "audio_chunk", "pcm_data": "cGNt"},
    ]
    refresh = {
        "clientContent": {
            "turns": [{"role": "user", "parts": [{"text": "souvenir chien"}]}],
            "turnComplete": False,
        }
    }
    monkeypatch.setattr(
        server,
        "build_live_query_brain_refresh_message",
        lambda _db, user, query, version: refresh
        if (user, query, version) == ("creator", "Parle-moi du chien", 1)
        else pytest.fail("unexpected audio preflight query"),
    )

    provider = run([
        {"serverContent": {"inputTranscription": {"text": "Parle-moi du chien"}}},
        {"serverContent": {"turnComplete": True}},
    ])

    refresh_index = provider.sent.index(refresh)
    audio_index = next(
        index for index, message in enumerate(provider.sent)
        if message.get("realtimeInput", {}).get("audio", {}).get("data") == "cGNt"
    )
    assert refresh_index < audio_index
    assert {"type": "audio_context_ready"} in client.sent
    # The browser transcript is a retrieval hint only; the provider transcript
    # remains the durable source of the confirmed user turn.
    assert calls["learning"] == [("creator", "Parle-moi du chien")]


def test_websocket_bridge_refreshes_persisted_brain_before_releasing_next_turn(
    live_bridge, monkeypatch
):
    run, _calls, _client = live_bridge
    snapshots = [
        {
            "snapshot_version": "34.0",
            "statistics": {"totals": {"memories": 1}},
            "vocabulary": [{"word": "bonjour", "state": "usable"}],
        },
        {
            "snapshot_version": "34.0",
            "statistics": {"totals": {"memories": 2}},
            "vocabulary": [
                {"word": "bonjour", "state": "usable"},
                {"word": "merci", "state": "usable"},
            ],
        },
    ]
    snapshot_calls = []

    def read_snapshot(_db, _user, limit=8, query=None):
        snapshot_calls.append((limit, query))
        return snapshots.pop(0)

    word_reads = iter([
        ["bonjour"],  # initial session vocabulary
        ["bonjour"],  # speech gate for the completed assistant turn
        ["bonjour", "merci"],  # refreshed persisted vocabulary
    ])
    monkeypatch.setattr(server, "get_shared_brain_snapshot", read_snapshot)
    monkeypatch.setattr(
        server, "get_repeatable_words", lambda _db, _user: next(word_reads)
    )

    provider = run([
        {"serverContent": {"inputTranscription": {"text": "Merci"}}},
        {"serverContent": {"turnComplete": True}},
    ])

    refresh_messages = [
        message["clientContent"]
        for message in provider.sent
        if "clientContent" in message
        and message["clientContent"].get("turnComplete") is False
    ]
    assert len(refresh_messages) == 1
    refresh_text = refresh_messages[0]["turns"][0]["parts"][0]["text"]
    assert "MISE À JOUR DU CERVEAU PARTAGÉ" in refresh_text
    assert "merci" in refresh_text
    assert snapshot_calls == [(8, None), (8, "Merci")]
    assert any(item.get("type") == "turn_complete" for item in _client.sent)


def test_websocket_bridge_closes_instead_of_continuing_with_stale_brain_context(
    live_bridge, monkeypatch
):
    run, calls, client = live_bridge
    snapshot_reads = 0

    def fail_refresh(_db, _user, limit=8, query=None):
        nonlocal snapshot_reads
        snapshot_reads += 1
        if snapshot_reads == 1:
            return {
                "snapshot_version": "34.0",
                "statistics": {"totals": {}},
                "vocabulary": [],
            }
        raise RuntimeError("simulated shared brain read failure")

    monkeypatch.setattr(server, "get_shared_brain_snapshot", fail_refresh)
    run([
        {"serverContent": {"inputTranscription": {"text": "Bonjour"}}},
        {"serverContent": {"turnComplete": True}},
    ])

    assert calls["learning"] == [("creator", "Bonjour")]
    assert calls["conversations"] == [
        ("creator", "Bonjour", "", {"source": "gemini_live"})
    ]
    assert any(code == server.status.WS_1011_INTERNAL_ERROR for code, _ in client.closed)
    assert not any(item.get("type") == "turn_complete" for item in client.sent)
    assert any(item.get("type") == "error" for item in client.sent)


def test_live_brain_refresh_message_is_incremental_and_does_not_start_a_model_turn():
    message = server.build_live_brain_refresh_message(
        {"snapshot_version": "34.0", "statistics": {"totals": {}}, "vocabulary": []},
        ["merci"],
        ["ancien"],
        3,
    )

    assert message["clientContent"]["turnComplete"] is False
    text = message["clientContent"]["turns"][0]["parts"][0]["text"]
    assert "nouveaux mots validés" in text
    assert "merci" in text
    assert "ne plus les employer" in text
    assert "ancien" in text


def test_websocket_bridge_holds_next_user_input_until_refresh_is_sent(
    live_bridge, monkeypatch
):
    run, _calls, client = live_bridge
    snapshots = [
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 0}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 1}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 2}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 2}}, "vocabulary": []},
    ]
    monkeypatch.setattr(
        server, "get_shared_brain_snapshot",
        lambda _db, _user, limit=8, query=None: snapshots.pop(0),
    )
    client.coordinate_refresh = True
    client.incoming_payloads = [
        {"action": "text", "text": "premier"},
        {"action": "text", "text": "suivant"},
    ]

    provider = run([
        {"serverContent": {"turnComplete": True}},
    ])

    refresh_indexes = [
        index for index, message in enumerate(provider.sent)
        if message.get("clientContent", {}).get("turnComplete") is False
    ]
    refresh_index = refresh_indexes[1]
    next_input_index = next(
        index for index, message in enumerate(provider.sent)
        if message.get("realtimeInput", {}).get("text") == "suivant"
    )
    assert refresh_index < next_input_index

def test_live_tool_response_precedes_brain_refresh_and_next_user_input(
    live_bridge, monkeypatch,
):
    run, _calls, client = live_bridge
    snapshots = [
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 0}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 1}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 2}}, "vocabulary": []},
        {"snapshot_version": "34.0", "statistics": {"totals": {"memories": 2}}, "vocabulary": []},
    ]
    monkeypatch.setattr(
        server, "get_shared_brain_snapshot",
        lambda _db, _user, limit=8, query=None: snapshots.pop(0),
    )
    monkeypatch.setattr(server, "get_repeatable_words", lambda _db, _user: [])
    monkeypatch.setattr(
        server, "execute_tool",
        lambda name, args, user_id, **kwargs: {
            "ok": True, "name": name, "user": user_id,
        },
    )

    client.coordinate_refresh = True
    client.incoming_payloads = [
        {"action": "text", "text": "premier"},
        {"action": "text", "text": "suivant"},
    ]
    provider = run([
        {
            "toolCall": {"functionCalls": [{
                "id": "ordered-call",
                "name": "get_shared_brain_state",
                "args": {},
            }]},
            "serverContent": {
                "inputTranscription": {"text": "Rappelle-toi"},
                "turnComplete": True,
            },
        },
    ])

    tool_response_index = next(
        index for index, message in enumerate(provider.sent)
        if "toolResponse" in message
    )
    refresh_index = next(
        index for index, message in enumerate(provider.sent)
        if index > tool_response_index
        and message.get("clientContent", {}).get("turnComplete") is False
    )
    next_input_index = next(
        index for index, message in enumerate(provider.sent)
        if message.get("realtimeInput", {}).get("text") == "suivant"
    )

    assert tool_response_index < refresh_index < next_input_index
    assert provider.sent[tool_response_index]["toolResponse"]["functionResponses"][0]["id"] == "ordered-call"
    assert client.second_input_received.is_set()
    assert any(item.get("type") == "turn_complete" for item in client.sent)




def test_websocket_bridge_persists_rate_limited_video_frame_receipt_with_provenance(
    live_bridge, monkeypatch
):
    run, calls, client = live_bridge
    client.incoming_payloads = [{
        "action": "video_frame",
        "data": "YWJj",
        "mime_type": "image/jpeg",
    }]
    monkeypatch.setattr(server, "live_visual_observation_due", lambda *_args: True)

    run([{"serverContent": {"turnComplete": True}}])

    visual = [
        item for item in calls["observations"]
        if item[1] == "vision"
        and item[3] == "live_camera_frame_received_by_server"
    ]
    assert len(visual) == 1
    metadata = visual[0][4]["metadata"]
    assert metadata["session_id"]
    assert metadata["frame_sequence"] == 1
    assert metadata["image_bytes_persisted"] is False
    assert metadata["semantic_analysis_performed"] is False


def test_live_turn_storage_failure_never_releases_uncommitted_assistant_audio(
    live_bridge, monkeypatch, caplog
):
    run, _calls, client = live_bridge
    save_attempts = []

    def fail_completed_turn_once(user, user_text, assistant_text, **kwargs):
        source = kwargs.get("source")
        save_attempts.append((source, user_text, assistant_text))
        if source == "gemini_live":
            raise RuntimeError("simulated completed-turn commit failure")

    monkeypatch.setattr(server, "save_conversation_turn", fail_completed_turn_once)
    monkeypatch.setattr(server, "get_skills_summary", lambda _user: {"average_level": 3})

    run([
        {"serverContent": {"inputTranscription": {"text": "Bonjour"}}},
        {"serverContent": {
            "outputTranscription": {"text": "Bonjour"},
            "modelTurn": {"parts": [{
                "inlineData": {
                    "data": "YXVkaW8=",
                    "mimeType": "audio/pcm;rate=24000",
                }
            }]},
            "turnComplete": True,
        }},
    ])

    assert save_attempts == [
        ("gemini_live", "Bonjour", "Bonjour"),
        ("gemini_live_interrupted", "Bonjour", ""),
    ]
    assert not any(item.get("type") == "audio_stream" for item in client.sent)
    assert not any(
        item.get("type") == "text" and item.get("text") == "Bonjour"
        for item in client.sent
    )
    assert any(item.get("type") == "error" for item in client.sent)
    assert "simulated completed-turn commit failure" in caplog.text
