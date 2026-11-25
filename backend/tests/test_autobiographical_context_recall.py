"""Query-relevant autobiographical recall must reach the shared identity context."""
from __future__ import annotations

from contextlib import contextmanager

import server


def test_autobiographical_context_prioritizes_relevant_older_episodes(monkeypatch):
    calls = {}

    @contextmanager
    def fake_db_connection():
        yield object()

    def fake_sync(_db, user_id):
        calls["sync_user"] = user_id
        return {"inserted": 0}

    def fake_recent(_db, user_id, limit=30):
        calls["recent"] = (user_id, limit)
        return [
            {"id": 12, "source_conversation_id": 12, "actor": "user",
             "happened_at": "2026-11-25T10:00:00Z", "content": "Discussion récente sans rapport"},
            {"id": 11, "source_conversation_id": 11, "actor": "assistant",
             "happened_at": "2026-11-25T09:00:00Z", "content": "Réponse récente"},
        ]

    def fake_search(_db, user_id, query, limit=10):
        calls["search"] = (user_id, query, limit)
        return [
            {"id": 2, "source_conversation_id": 2, "actor": "user",
             "happened_at": "2026-11-01T10:00:00Z", "content": "Mon horloge rouge est dans le salon",
             "relevance_score": 4.35, "matched_terms": ["horloge", "rouge"],
             "dialogue_context": False},
            {"id": 3, "source_conversation_id": 3, "actor": "assistant",
             "happened_at": "2026-11-01T10:00:00Z", "content": "Tu m'as montré ton horloge",
             "relevance_score": 0.0, "matched_terms": [], "dialogue_context": True},
        ]

    monkeypatch.setattr(server, "db_connection", fake_db_connection)
    monkeypatch.setattr(server, "sync_autobiographical_events", fake_sync)
    monkeypatch.setattr(server, "list_autobiographical_events", fake_recent)
    monkeypatch.setattr(server, "search_autobiographical_events", fake_search)

    result = server.build_autobiographical_context(
        "creator", query="où est mon horloge rouge"
    )

    assert calls["sync_user"] == "creator"
    assert calls["recent"] == ("creator", 8)
    assert calls["search"] == ("creator", "où est mon horloge rouge", 5)
    assert result.index("Mon horloge rouge") < result.index("Discussion récente")
    assert "rappel pertinent" in result
    assert "termes=horloge, rouge" in result
    assert "réponse liée au même tour" in result
    assert result.count("Mon horloge rouge") == 1


def test_autobiographical_context_without_query_uses_recent_only(monkeypatch):
    calls = []

    @contextmanager
    def fake_db_connection():
        yield object()

    monkeypatch.setattr(server, "db_connection", fake_db_connection)
    monkeypatch.setattr(server, "sync_autobiographical_events", lambda *_args: None)
    monkeypatch.setattr(
        server, "list_autobiographical_events",
        lambda *_args, **_kwargs: [
            {"id": 1, "source_conversation_id": 1, "actor": "user",
             "happened_at": "t1", "content": "Épisode récent"}
        ],
    )

    def unexpected_search(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("Une recherche vide ne doit pas être lancée.")

    monkeypatch.setattr(server, "search_autobiographical_events", unexpected_search)
    result = server.build_autobiographical_context("creator", query="")

    assert "Épisode récent" in result
    assert "épisode récent" in result
    assert calls == []


def test_autobiographical_context_rejects_invalid_query_before_database(monkeypatch):
    def unexpected_db_connection():
        raise AssertionError("La base ne doit pas être ouverte pour une requête invalide.")

    monkeypatch.setattr(server, "db_connection", unexpected_db_connection)
    try:
        server.build_autobiographical_context("creator", query=object())
    except ValueError:
        pass
    else:
        raise AssertionError("Une requête non textuelle doit être refusée.")
