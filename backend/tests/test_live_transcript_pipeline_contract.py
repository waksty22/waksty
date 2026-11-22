"""Contract tests for fragmented Gemini Live transcript handling.

These tests exercise the same bounded merge and completion gates used by the
WebSocket bridge, without opening a provider connection or touching storage.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from learning.live_turn import confirmed_live_transcript


def test_live_transcript_fragments_merge_without_repeating_overlap():
    transcript = ""

    for fragment in ("Bonjour tout", "tout le monde", "comment", "ça va ?"):
        transcript = server._merge_bounded_live_transcript(
            transcript, fragment
        )
        assert transcript is not None

    assert transcript == "Bonjour tout le monde comment ça va ?"


def test_live_transcript_retransmitted_prefix_does_not_create_new_segment():
    previous = "Bonjour tout le monde"
    merged = server._merge_bounded_live_transcript(
        previous, "Bonjour tout"
    )

    assert merged == previous
    assert server._new_live_transcript_segment(previous, merged) == ""


def test_live_transcript_incremental_chunk_exposes_only_new_words():
    previous = "Bonjour tout"
    merged = server._merge_bounded_live_transcript(
        previous, "Bonjour tout le monde"
    )

    assert merged == "Bonjour tout le monde"
    assert server._new_live_transcript_segment(previous, merged) == "le monde"


def test_fragmented_transcript_is_not_learning_evidence_before_turn_complete():
    transcript = ""
    for fragment in ("Je voudrais", " apprendre", " le mot bonjour"):
        transcript = server._merge_bounded_live_transcript(
            transcript, fragment
        )
        assert transcript is not None
        assert confirmed_live_transcript(
            transcript, turn_complete=False
        ) == ""

    assert confirmed_live_transcript(
        transcript, turn_complete=True
    ) == "Je voudrais apprendre le mot bonjour"


def test_oversized_fragment_or_accumulated_turn_is_rejected():
    assert server._merge_bounded_live_transcript(
        "", "x" * (server.MAX_LIVE_TEXT_CHUNK_CHARS + 1)
    ) is None

    assert server._merge_bounded_live_transcript(
        "x" * server.MAX_LIVE_TRANSCRIPT_CHARS, "suite"
    ) is None
