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

def test_live_query_refresh_uses_current_user_text_before_provider_input(monkeypatch):
    calls = []

    def snapshot(db, user_id, limit, query):
        calls.append((db, user_id, limit, query))
        return {"world_entities": [{"properties": {"label": "Éléphant"}}]}

    monkeypatch.setattr(server, "get_shared_brain_snapshot", snapshot)
    monkeypatch.setattr(
        server, "build_live_brain_refresh_message",
        lambda value, added, removed, version: {
            "snapshot": value, "added": added, "removed": removed,
            "version": version,
        },
    )

    result = server.build_live_query_brain_refresh_message(
        "temporary-db", "creator", "Parle-moi de l'éléphant", 3
    )

    assert calls == [(
        "temporary-db", "creator", 8, "Parle-moi de l'éléphant"
    )]
    assert result["snapshot"]["world_entities"][0]["properties"]["label"] == "Éléphant"
    assert result["version"] == 3


def test_live_query_refresh_skips_empty_query_without_reading_database(monkeypatch):
    monkeypatch.setattr(
        server, "get_shared_brain_snapshot",
        lambda *args, **kwargs: pytest.fail("empty queries must not read the brain"),
    )
    assert server.build_live_query_brain_refresh_message(
        "temporary-db", "creator", "   ", 1
    ) is None
