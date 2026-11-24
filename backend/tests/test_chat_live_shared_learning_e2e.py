"""End-to-end proof that Chat and Gemini Live share one durable learning store.

The provider is a deterministic fake WebSocket. The application Chat handler and
actual FastAPI Live WebSocket route are exercised against an isolated SQLite file.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

class FakeClientWebSocket:
    def __init__(self, payloads):
        self.payloads = list(payloads)
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
    def __init__(
        self,
        user_text: str = "",
        assistant_text: str = "",
        *,
        turn_complete: bool = True,
    ):
        self.user_text = user_text
        self.assistant_text = assistant_text
        self.turn_complete = turn_complete
        self.sent: list[dict] = []
        self._ready = asyncio.Event()
        self._yielded = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if isinstance(payload.get("realtimeInput"), dict):
            self._ready.set()

    async def recv(self) -> str:
        return json.dumps({"setupComplete": {}})

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._yielded:
            raise StopAsyncIteration
        await asyncio.wait_for(self._ready.wait(), timeout=5)
        self._yielded = True
        server_content = {
            "inputTranscription": {"text": self.user_text},
            "outputTranscription": {"text": self.assistant_text},
            "modelTurn": {"parts": [{"text": self.assistant_text}]},
        }
        if self.turn_complete:
            server_content["turnComplete"] = True
        return json.dumps({"serverContent": server_content})

    @property
    def initial_history_text(self) -> str:
        for payload in self.sent:
            client_content = payload.get("clientContent")
            if not isinstance(client_content, dict):
                continue
            chunks = []
            for turn in client_content.get("turns", []):
                for part in turn.get("parts", []):
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
            return "\n".join(chunks)
        return ""


def test_chat_and_live_share_persisted_learning_and_interrupted_turns_are_history_only(
    monkeypatch, tmp_path
):
    import server
    from cognition.shared_brain import get_shared_brain_snapshot

    database_path = tmp_path / "shared-chat-live.sqlite3"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-provider-key")
    server.init_db()

    replies = iter(("zorbital", "velociraptor"))

    async def fake_chat_provider(contents, user_id, query=""):
        return {"parts": [{"text": next(replies)}]}

    monkeypatch.setattr(server, "call_gemini", fake_chat_provider)

    provider_sockets: list[FakeGeminiLiveSocket] = []

    @asynccontextmanager
    async def fake_supervised_gemini_connection(websocket):
        yield provider_sockets.pop(0)

    monkeypatch.setattr(
        server, "supervised_gemini_connection", fake_supervised_gemini_connection
    )

    def run_live_session(user_id: str, fake_socket: FakeGeminiLiveSocket):
        provider_sockets.append(fake_socket)
        ticket = server.live_ws_tickets.issue(user_id)
        fake_client = FakeClientWebSocket([
            {"action": "audio_chunk", "pcm_data": "AQID"}
        ])
        asyncio.run(server.websocket_endpoint(fake_client, ticket=ticket))
        assert fake_client.accepted
        assert any(item.get("type") == "connected" for item in fake_client.sent)
        return fake_client.sent, fake_socket.initial_history_text

    # Chat -> vocabulary: this exercises the real API handler and run_brain,
    # with only the external Gemini HTTP provider replaced by a deterministic fake.
    chat_one = asyncio.run(
        server.api_chat(server.ChatRequest(message="zorbital"), auth="creator")
    )
    assert chat_one["reply"] == "zorbital"

    # Close and reopen the database connection before inspecting shared memory.
    with server.db_connection() as reopened:
        snapshot_after_chat = get_shared_brain_snapshot(reopened, "creator")
        assert "zorbital" in {
            row["word"] for row in snapshot_after_chat["vocabulary"]
        }

    # Chat -> Live: the real Live endpoint receives the same persisted word in
    # its initial context, then confirms and commits a new spoken word exactly once.
    live_socket = FakeGeminiLiveSocket("velociraptor", "zorbital")
    live_messages, live_context = run_live_session("creator", live_socket)
    assert "zorbital" in live_context
    assert "velociraptor" not in live_context
    assert any(item.get("type") == "turn_complete" for item in live_messages)
    assert any(
        item.get("type") == "text" and item.get("text") == "zorbital"
        for item in live_messages
    )

    with server.db_connection() as reopened:
        snapshot_after_live = get_shared_brain_snapshot(reopened, "creator")
        words = {row["word"] for row in snapshot_after_live["vocabulary"]}
        assert {"zorbital", "velociraptor"} <= words
        assert reopened.execute(
            "SELECT COUNT(*) FROM journal WHERE user_id=? AND kind='gemini_live'",
            ("creator",),
        ).fetchone()[0] == 1
        assert reopened.execute(
            "SELECT COUNT(*) FROM sensory_observations "
            "WHERE user_id=? AND source='gemini_live_transcription'",
            ("creator",),
        ).fetchone()[0] == 1

    # Live -> Chat after a fresh connection: Chat can now repeat the word
    # that was first heard and committed through Gemini Live.
    chat_two = asyncio.run(
        server.api_chat(
            server.ChatRequest(message="velociraptor"),
            auth="creator",
        )
    )
    assert chat_two["reply"] == "velociraptor"

    # A second real Live endpoint session reconstructs its initial context
    # from the reopened database and sees both confirmed words.
    reconnect_socket = FakeGeminiLiveSocket("", "", turn_complete=True)
    reconnect_messages, reconnect_context = run_live_session(
        "creator", reconnect_socket
    )
    assert "zorbital" in reconnect_context
    assert "velociraptor" in reconnect_context
    assert any(item.get("type") == "turn_complete" for item in reconnect_messages)

    # A separate owner context on the same isolated database must not receive
    # the creator's transcript or vocabulary through the actual Live endpoint.
    other_user_socket = FakeGeminiLiveSocket("", "", turn_complete=True)
    owner_id = server.CHAPPIE_OWNER_ID
    monkeypatch.setattr(server, "CHAPPIE_OWNER_ID", "other-user")
    try:
        _, other_user_context = run_live_session(
            "other-user", other_user_socket
        )
    finally:
        monkeypatch.setattr(server, "CHAPPIE_OWNER_ID", owner_id)
    assert "zorbital" not in other_user_context
    assert "velociraptor" not in other_user_context

    # An interrupted Live transcript remains conversation history, but must
    # not change vocabulary, emotions, mood events, or sensory observations.
    with server.db_connection() as before_db:
        before_counts = {
            table: before_db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                ("creator",),
            ).fetchone()[0]
            for table in ("personal_vocabulary", "mood_events", "affective_history", "sensory_observations")
        }
        before_emotions = tuple(before_db.execute(
            "SELECT joy, fear, curiosity, frustration, sadness, energy "
            "FROM emotional_state WHERE user_id=?",
            ("creator",),
        ).fetchone())

    interrupted_socket = FakeGeminiLiveSocket(
        "interrompuword", "zorbital", turn_complete=False
    )
    interrupted_messages, _ = run_live_session(
        "creator", interrupted_socket
    )
    assert not any(item.get("type") == "turn_complete" for item in interrupted_messages)

    with server.db_connection() as reopened:
        after_counts = {
            table: reopened.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                ("creator",),
            ).fetchone()[0]
            for table in before_counts
        }
        after_emotions = tuple(reopened.execute(
            "SELECT joy, fear, curiosity, frustration, sadness, energy "
            "FROM emotional_state WHERE user_id=?",
            ("creator",),
        ).fetchone())
        assert after_counts == before_counts
        assert after_emotions == before_emotions
        assert reopened.execute(
            "SELECT COUNT(*) FROM personal_vocabulary "
            "WHERE user_id=? AND word='interrompuword'",
            ("creator",),
        ).fetchone()[0] == 0
        assert reopened.execute(
            "SELECT COUNT(*) FROM journal "
            "WHERE user_id=? AND kind='gemini_live_interrupted'",
            ("creator",),
        ).fetchone()[0] == 1
        assert reopened.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE user_id=? AND content LIKE '%interrompuword%'",
            ("creator",),
        ).fetchone()[0] == 1


class TwoTurnFakeGeminiLiveSocket(FakeGeminiLiveSocket):
    """Provider double that returns two turns in one uninterrupted Live session."""

    def __init__(self):
        super().__init__()
        self._turn_queue = asyncio.Queue()
        self._input_count = 0
        self.refresh_seen_before_second_input = False

    async def send(self, raw: str) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if isinstance(payload.get("clientContent"), dict):
            # The initial history is sent before the first input. The later
            # clientContent message is the in-session shared-brain delta.
            if self._input_count == 1:
                self.refresh_seen_before_second_input = True
        if isinstance(payload.get("realtimeInput"), dict):
            self._input_count += 1
            if self._input_count == 2:
                assert self.refresh_seen_before_second_input, (
                    "second user input reached Gemini before shared-brain refresh"
                )
            if self._input_count == 1:
                user_text, assistant_text = "zorbital", "oui"
            elif self._input_count == 2:
                user_text, assistant_text = "zorbital", "zorbital"
            else:
                raise AssertionError("unexpected third input in two-turn test")
            content = {
                "inputTranscription": {"text": user_text},
                "outputTranscription": {"text": assistant_text},
                "modelTurn": {"parts": [{"text": assistant_text}]},
                "turnComplete": True,
            }
            await self._turn_queue.put(json.dumps({"serverContent": content}))
            if self._input_count == 2:
                await self._turn_queue.put(None)

    async def __anext__(self) -> str:
        item = await asyncio.wait_for(self._turn_queue.get(), timeout=5)
        if item is None:
            raise StopAsyncIteration
        return item


def test_live_refreshes_shared_brain_between_turns_without_reconnecting(
    monkeypatch, tmp_path
):
    """A word learned on turn one is sent to the same provider session before turn two."""
    import server

    database_path = tmp_path / "live-in-session-refresh.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-only-provider-key")
    server.init_db()

    provider = TwoTurnFakeGeminiLiveSocket()

    @asynccontextmanager
    async def fake_connection(websocket):
        yield provider

    monkeypatch.setattr(server, "supervised_gemini_connection", fake_connection)

    fake_client = FakeClientWebSocket([
        {"action": "audio_chunk", "pcm_data": "AQID"},
        {"action": "audio_chunk", "pcm_data": "BAUG"},
    ])
    ticket = server.live_ws_tickets.issue("creator")
    asyncio.run(server.websocket_endpoint(fake_client, ticket=ticket))

    assert fake_client.accepted
    assert not fake_client.closed
    assert provider._input_count == 2
    assert provider.refresh_seen_before_second_input
    assert any(
        item.get("type") == "turn_complete" for item in fake_client.sent
    )
    refresh_messages = [
        payload for payload in provider.sent
        if isinstance(payload.get("clientContent"), dict)
        and payload.get("clientContent", {}).get("turns")
    ]
    # Initial context plus at least one incremental brain update in-session.
    assert len(refresh_messages) >= 2
    incremental_text = json.dumps(refresh_messages[1], ensure_ascii=False)
    assert "zorbital" in incremental_text

    with server.db_connection() as db:
        words = {
            row["word"] for row in db.execute(
                "SELECT word FROM personal_vocabulary WHERE user_id=?",
                ("creator",),
            ).fetchall()
        }
    assert "zorbital" in words
