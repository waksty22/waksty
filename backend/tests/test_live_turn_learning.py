from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.live_turn import confirmed_live_transcript


def test_live_learning_accepts_only_a_completed_nonempty_transcript():
    assert confirmed_live_transcript(
        "  Bonjour Chappie  ", turn_complete=True
    ) == "Bonjour Chappie"
    assert confirmed_live_transcript("", turn_complete=True) == ""
    assert confirmed_live_transcript("   ", turn_complete=True) == ""


def test_live_learning_does_not_promote_interrupted_or_disconnected_turns():
    for transcript in ("Bonjour", "Bonjour tout le monde"):
        assert confirmed_live_transcript(
            transcript, turn_complete=False
        ) == ""


def test_live_learning_rejects_non_text_and_oversized_transcripts():
    for value in (None, 123, True, b"Bonjour", {"text": "Bonjour"}):
        assert confirmed_live_transcript(value, turn_complete=True) == ""
    assert confirmed_live_transcript(
        "x" * 100_001, turn_complete=True
    ) == ""


def test_live_learning_requires_literal_true_completion_flag():
    for flag in (None, False, 1, "true", [], {}):
        assert confirmed_live_transcript(
            "Bonjour", turn_complete=flag
        ) == ""
