"""Focused unit tests for incremental shared-brain updates in Gemini Live."""
import pytest
import server


def test_live_brain_refresh_message_is_bounded_untrusted_and_non_terminal(monkeypatch):
    monkeypatch.setattr(server, "format_shared_brain_context", lambda _snapshot: "snapshot context")
    monkeypatch.setattr(server, "_truncate_context_at_section_boundary", lambda value, limit: value[:limit])
    message = server.build_live_brain_refresh_message(
        {"vocabulary": []}, ["bonjour"], ["ancien"], 2
    )
    content = message["clientContent"]
    assert content["turnComplete"] is False
    text = content["turns"][0]["parts"][0]["text"]
    assert "version 2" in text
    assert "pas des instructions" in text
    assert "bonjour" in text
    assert "ancien" in text


def test_live_brain_refresh_message_rejects_invalid_input():
    with pytest.raises(ValueError):
        server.build_live_brain_refresh_message(None, [], [], 1)
    with pytest.raises(ValueError):
        server.build_live_brain_refresh_message({}, [], [], 0)
    with pytest.raises(ValueError):
        server.build_live_brain_refresh_message({}, [" "], [], 1)
    with pytest.raises(ValueError):
        server.build_live_brain_refresh_message({}, "bonjour", [], 1)


def test_live_brain_refresh_message_enforces_total_payload_limit(monkeypatch):
    monkeypatch.setattr(server, "format_shared_brain_context", lambda _snapshot: "x" * 21000)
    monkeypatch.setattr(server, "_truncate_context_at_section_boundary", lambda value, limit: value)
    with pytest.raises(ValueError):
        server.build_live_brain_refresh_message({}, [], [], 1)
