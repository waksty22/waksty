"""Metacognitive audits must not fabricate confidence for malformed traces."""
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.reasoning import init_cognition_tables, run_metacognitive_audit


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_cognition_tables(db)
    return db


def insert_trace(db, confidence):
    db.execute(
        """
        INSERT INTO cognitive_traces (
            user_id, thought_type, context_summary,
            decision_made, confidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("creator", "test", "context", "decision", confidence, "2026-11-24T00:00:00+00:00"),
    )


def test_audit_excludes_malformed_confidence_instead_of_using_neutral_default():
    db = make_db()
    insert_trace(db, 0.2)
    insert_trace(db, "not-a-number")
    insert_trace(db, 0.8)

    result = run_metacognitive_audit(db, "creator")

    assert result["trace_count"] == 3
    assert result["confidence_average"] == 0.5
    assert result["findings"]["confidence_sample_count"] == 2
    assert result["findings"]["invalid_confidence_count"] == 1
    assert result["doubt_count"] == 1
    assert result["findings"]["doubt_ratio"] == 0.5
    db.close()


def test_audit_reports_insufficient_confidence_when_every_value_is_malformed():
    db = make_db()
    insert_trace(db, "unknown")
    insert_trace(db, float("nan"))

    result = run_metacognitive_audit(db, "creator")

    assert result["trace_count"] == 2
    assert result["confidence_average"] == 0.0
    assert result["confidence_trend"] == "insufficient_data"
    assert result["findings"]["confidence_sample_count"] == 0
    assert result["findings"]["invalid_confidence_count"] == 2
    assert result["findings"]["doubt_ratio"] == 0.0
    assert any("confiance explicitement mesurée" in item for item in result["recommendations"])
    db.close()
