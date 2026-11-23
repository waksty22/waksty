"""Helpers for gating Gemini Live learning on complete provider turns."""

from __future__ import annotations

MAX_CONFIRMED_LIVE_TRANSCRIPT_CHARS = 100_000


def confirmed_live_transcript(
    transcript: object,
    *,
    turn_complete: bool,
) -> str:
    """Return a bounded transcript only after an explicit completed turn.

    Interrupted/disconnected sessions may still be persisted as conversation
    history, but their partial text must not be promoted to learning evidence.
    """
    if turn_complete is not True or not isinstance(transcript, str):
        return ""
    normalized = transcript.strip()
    if not normalized or len(normalized) > MAX_CONFIRMED_LIVE_TRANSCRIPT_CHARS:
        return ""
    return normalized
