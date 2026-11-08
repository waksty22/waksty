"""V50.14 — contextual knowledge recall in written chat and shared prompt."""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SERVER = (BACKEND / "server.py").read_text(encoding="utf-8")


def test_identity_prompt_accepts_current_user_query():
    assert 'def get_identity_prompt(user_id: str, query: str = "") -> str:' in SERVER
    assert "query=query, limit=10" in SERVER
    assert "format_acquired_knowledge_context(" in SERVER


def test_written_chat_passes_current_message_to_gemini_context():
    assert 'query: str = "",' in SERVER[SERVER.index("async def call_gemini("):SERVER.index("async def call_gemini(") + 220]
    assert "get_identity_prompt(user_id, query=query)" in SERVER
    call = SERVER[SERVER.index("model_response = await call_gemini"):SERVER.index("model_response = await call_gemini") + 220]
    assert "query=message" in call


def test_live_keeps_shared_prompt_compatible_without_user_turn_query():
    live = SERVER[SERVER.index("identity_prompt = get_identity_prompt(user_id)"):]
    assert "identity_prompt = get_identity_prompt(user_id)" in live
