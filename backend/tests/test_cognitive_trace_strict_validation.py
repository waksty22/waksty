"""Strict input validation for persisted cognitive traces."""
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest
from cognition.reasoning import init_cognition_tables, log_cognitive_trace


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_cognition_tables(connection)
    yield connection
    connection.close()


def record(db, **overrides):
    values = {
        "user_id": "creator",
        "thought_type": "memory_uncertainty",
        "context_summary": "Résumé neutre et borné du contexte mémoire.",
        "decision_made": "Demander une vérification.",
        "confidence": 0.25,
    }
    values.update(overrides)
    return log_cognitive_trace(db, **values)


@pytest.mark.parametrize("field", ["thought_type", "context_summary", "decision_made"])
@pytest.mark.parametrize("bad", [None, 7, True, {}, []])
def test_trace_text_fields_reject_non_text_without_writing(db, field, bad):
    with pytest.raises(ValueError):
        record(db, **{field: bad})
    assert db.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["thought_type", "context_summary", "decision_made"])
def test_trace_text_fields_reject_oversized_values_without_truncating(db, field):
    maximum = 100 if field == "thought_type" else 12000
    with pytest.raises(ValueError):
        record(db, **{field: "x" * (maximum + 1)})
    assert db.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0] == 0


@pytest.mark.parametrize("bad", ["0.2", True, None, {}, [], float("nan"), float("inf"), -0.1, 1.1])
def test_trace_confidence_rejects_coercion_and_non_finite_values(db, bad):
    with pytest.raises(ValueError):
        record(db, confidence=bad)
    assert db.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0] == 0


def test_trace_accepts_explicit_neutral_confidence(db):
    trace = record(db, confidence=0.0)
    assert trace["confidence"] == 0.0
    assert db.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0] == 1
