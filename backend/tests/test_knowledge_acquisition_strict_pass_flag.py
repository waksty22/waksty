"""Strict numeric validation for supervised skill pass flags."""
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from memory.knowledge_acquisition import retrieve_acquired_knowledge


def test_float_one_is_not_exposed_as_a_successful_integer_pass():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE memories_v19 (
            id INTEGER PRIMARY KEY, user_id TEXT, category TEXT, content TEXT,
            source_type TEXT, confidence REAL, importance INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE autobiographical_events (
            id INTEGER PRIMARY KEY, user_id TEXT, actor TEXT, event_type TEXT,
            content TEXT, happened_at TEXT, source_conversation_id INTEGER
        );
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY, user_id TEXT, test_name TEXT,
            passed REAL, score REAL, details TEXT, tested_at TEXT
        );
    """)
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Évaluation de contrôle.",
    }
    db.execute(
        """INSERT INTO competency_tests
           VALUES (1, 'creator', 'tete:vision', 1.0, 95, ?, '2026-11-27')""",
        (json.dumps(details),),
    )

    result = retrieve_acquired_knowledge(db, "creator")
    skill = next(item for item in result["items"] if item["kind"] == "skill_assessment")

    assert skill["status"] == "supervised_assessment_not_validated"
    assert skill["passed"] is False
    db.close()
