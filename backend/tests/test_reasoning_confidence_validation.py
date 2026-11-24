"""Confidence evaluation must preserve unknowns and reject coercion."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest
from cognition.reasoning import (
    evaluate_decision_doubt,
    evaluate_memory_relevance_doubt,
)


@pytest.mark.parametrize("bad", ["0.4", True, None, {}, [], float("nan"), float("inf"), -0.1, 1.1])
def test_decision_confidence_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        evaluate_decision_doubt(bad)


@pytest.mark.parametrize("bad", ["0.6", True, None, {}, [], float("nan"), float("inf"), -0.1, 1.1])
def test_decision_threshold_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        evaluate_decision_doubt(0.4, threshold=bad)


def test_memory_relevance_does_not_invent_confidence_for_missing_metadata():
    assert evaluate_memory_relevance_doubt([{"content": "souvenir sans confiance"}]) is None


def test_memory_relevance_uses_only_explicit_valid_confidence():
    result = evaluate_memory_relevance_doubt([
        {"confidence": "0.1"},
        {"confidence": True},
        {"confidence": 0.2},
        {"confidence": 0.8},
    ])
    assert result is not None
    assert result["confidence"] == 0.5


def test_memory_relevance_returns_unknown_when_all_confidences_are_invalid():
    assert evaluate_memory_relevance_doubt([
        {"confidence": "0.5"},
        {"confidence": float("nan")},
        {},
    ]) is None
