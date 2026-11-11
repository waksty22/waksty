import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnostics.conversation_persistence import (
    persistence_event_snapshot,
    record_persistence_event,
    reset_persistence_event_counters,
)


def test_persistence_counters_are_bounded_and_content_free():
    reset_persistence_event_counters()
    record_persistence_event("chat_received", "conversation")
    record_persistence_event("save_attempted", "conversation")
    record_persistence_event("save_committed", "conversation")
    record_persistence_event("save_failed", "gemini_live")
    record_persistence_event("private-message-content", "private-user-id")

    snapshot = persistence_event_snapshot()
    assert snapshot["conversation"] == {
        "chat_received": 1,
        "save_attempted": 1,
        "save_committed": 1,
    }
    assert snapshot["gemini_live"]["save_failed"] == 1
    assert "private-message-content" not in repr(snapshot)
    assert "private-user-id" not in repr(snapshot)


def test_snapshot_is_detached_from_internal_counters():
    reset_persistence_event_counters()
    record_persistence_event("save_attempted", "gemini_live")
    snapshot = persistence_event_snapshot()
    snapshot["gemini_live"]["save_attempted"] = 999
    assert persistence_event_snapshot()["gemini_live"]["save_attempted"] == 1
    reset_persistence_event_counters()
