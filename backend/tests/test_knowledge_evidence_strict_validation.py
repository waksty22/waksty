from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.knowledge_acquisition import retrieve_acquired_knowledge
from learning.causal_learning import init_causal_learning_tables, record_observation
from learning.perception_fusion import review_perception_fusion


def test_optional_missing_knowledge_tables_are_tolerated():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    result = retrieve_acquired_knowledge(db, "creator")
    assert result["items"] == []
    assert result["read_only"] is True
    db.close()


def test_knowledge_retrieval_does_not_hide_missing_columns():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE memories_v19 (user_id TEXT)")
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        retrieve_acquired_knowledge(db, "creator")
    db.close()


@pytest.mark.parametrize("confidence", ["0.7", "1", "0", True, None, {}, []])
def test_causal_confidence_rejects_implicit_or_invalid_types(confidence):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_causal_learning_tables(db)
    with pytest.raises(ValueError):
        record_observation(
            db, "creator", "un événement", "un résultat",
            confidence=confidence,
        )
    assert db.execute("SELECT COUNT(*) FROM causal_observations").fetchone()[0] == 0
    db.close()


@pytest.mark.parametrize("candidate_id", ["1", 1.0, True, None, {}, []])
def test_perception_review_rejects_coerced_candidate_ids(candidate_id):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    with pytest.raises(ValueError, match="Identifiant de rapprochement"):
        review_perception_fusion(
            db, "creator", candidate_id, "confirm", "preuve explicite"
        )
    db.close()


def test_perception_review_accepts_real_integer_id_only_after_lookup():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE perception_fusion_candidates (
            id INTEGER PRIMARY KEY, user_id TEXT, status TEXT, evidence_json TEXT
        )
    """)
    db.execute(
        "INSERT INTO perception_fusion_candidates VALUES (1,'creator','candidate','{}')"
    )
    result = review_perception_fusion(db, "creator", 1, "confirm", "preuve explicite")
    assert result["status"] == "confirmed"
    assert result["world_knowledge_promoted"] is False
    db.close()



def test_invalid_assessment_score_is_not_fabricated_as_zero():
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
            id INTEGER PRIMARY KEY, user_id TEXT, test_name TEXT, passed,
            score, details TEXT, tested_at TEXT
        );
        INSERT INTO competency_tests
            (id,user_id,test_name,passed,score,details,tested_at)
        VALUES
            (1,'creator','vocabulaire',1,'score inconnu',
             '{"source":"supervised_assessment","supervisor_approved":true}',
             '2026-11-24T00:00:00+00:00');
    """)
    result = retrieve_acquired_knowledge(db, "creator")
    assessment = result["items"][0]
    assert assessment["status"] == "supervised_assessment_not_validated"
    assert assessment["score"] is None
    db.close()
