"""Process-local, content-free diagnostics for conversation persistence."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

_ALLOWED_SOURCES = {
    "conversation",
    "gemini_live",
    "gemini_live_interrupted",
    "unknown",
}
_ALLOWED_EVENTS = {
    "chat_received",
    "chat_reply_ready",
    "save_attempted",
    "save_committed",
    "save_failed",
}
_lock = Lock()
_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def record_persistence_event(event: str, source: str = "unknown") -> None:
    """Increment a bounded counter; never retain user IDs or message contents."""
    safe_event = event if event in _ALLOWED_EVENTS else "unknown_event"
    safe_source = source if source in _ALLOWED_SOURCES else "unknown"
    with _lock:
        _counts[safe_source][safe_event] += 1


def persistence_event_snapshot() -> dict[str, Any]:
    """Return a detached snapshot of process-local counters."""
    with _lock:
        return {
            source: dict(sorted(events.items()))
            for source, events in sorted(_counts.items())
        }


def reset_persistence_event_counters() -> None:
    """Test helper; not exposed by the application API."""
    with _lock:
        _counts.clear()
