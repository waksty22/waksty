"""Reject malformed or coerced model tool arguments before memory access."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server


def test_execute_tool_rejects_non_object_arguments():
    result = server.execute_tool("search_memories", ["souvenir"], "creator")
    assert "error" in result


@pytest.mark.parametrize(
    "arguments",
    [
        {"content": 123},
        {"category": []},
        {"importance": True},
        {"importance": "3"},
        {"importance": 0},
        {"importance": 6},
        {"source_type": {}},
        {"confidence": "0.8"},
        {"confidence": True},
        {"tags": ["ok", 3]},
        {"content": "x" * 4001},
    ],
)
def test_remember_fact_rejects_coerced_or_invalid_fields(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(
        server, "remember",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"saved": True},
    )
    result = server.execute_tool(
        "remember_fact",
        {"content": "mon vélo rouge", **arguments},
        "creator",
        user_source_text="Je veux que tu mémorises mon vélo rouge.",
    )
    assert "error" in result or result.get("saved") is False
    assert calls == []


def test_remember_fact_accepts_valid_typed_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(
        server, "remember",
        lambda *args, **kwargs: calls.append(args) or {"saved": True},
    )
    result = server.execute_tool(
        "remember_fact",
        {
            "content": "mon vélo rouge",
            "category": "préférence",
            "importance": 3,
            "source_type": "taught",
            "confidence": 0.8,
            "tags": ["vélo"],
        },
        "creator",
        user_source_text="Je veux que tu mémorises mon vélo rouge.",
    )
    assert result == {"saved": True}
    assert calls == [("creator", "mon vélo rouge", "préférence", 3, "taught", 0.8, ["vélo"])]


@pytest.mark.parametrize("tool_name", [
    "search_memories",
    "retrieve_acquired_knowledge",
    "search_autobiographical_events",
])
@pytest.mark.parametrize("bad_query", [123, True, [], {}])
def test_memory_search_tools_reject_non_text_queries_before_storage(
    monkeypatch, tool_name, bad_query
):
    def unexpected_storage():
        raise AssertionError("Storage must not be opened for invalid tool arguments")

    monkeypatch.setattr(server, "db_connection", unexpected_storage)
    monkeypatch.setattr(
        server, "retrieve_memories",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Memory retrieval must not be called")
        ),
    )
    result = server.execute_tool(tool_name, {"query": bad_query}, "creator")
    assert "error" in result


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1", 0, -1])
def test_related_autobiographical_tool_rejects_coerced_ids_before_storage(
    monkeypatch, bad_id
):
    def unexpected_storage():
        raise AssertionError("Storage must not be opened for invalid IDs")

    monkeypatch.setattr(server, "db_connection", unexpected_storage)
    result = server.execute_tool(
        "find_related_autobiographical_events", {"event_id": bad_id}, "creator"
    )
    assert "error" in result
