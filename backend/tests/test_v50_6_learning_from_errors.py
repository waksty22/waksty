"""V50.6 — review of corrections without erasing prior experiment outcomes."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from learning.causal_learning import (
    init_causal_learning_tables,
    record_observation,
    propose_hypothesis,
    plan_experiment,
    evaluate_experiment,
    review_causal_learning,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_causal_learning_tables(db)
    return db


def make_hypothesis(db, user_id="creator"):
    observation = record_observation(
        db, user_id, "Une balle est lâchée", "Elle tombe",
        source_type="observed", confidence=0.8,
    )
    hypothesis = propose_hypothesis(
        db, user_id, observation["id"],
        "La balle tombe lorsqu'on la lâche",
        "La balle atteint le sol", confidence=0.4,
    )
    return hypothesis


def complete_test(db, user_id, hypothesis_id, evaluation, result):
    experiment = plan_experiment(
        db, user_id, hypothesis_id, "simulation",
        "Simulation contrôlée de chute", "La balle atteint le sol",
        supervisor_approved=True,
    )
    return evaluate_experiment(
        db, user_id, experiment["id"], result, evaluation
    )


def test_review_preserves_contradicted_then_supported_history_as_mixed():
    db = make_db()
    hypothesis = make_hypothesis(db)
    complete_test(db, "creator", hypothesis["id"], "contradicted",
                  "La balle ne tombe pas dans cette simulation.")
    complete_test(db, "creator", hypothesis["id"], "supported",
                  "La balle tombe dans une seconde simulation.")

    before = [
        tuple(row) for row in db.execute(
            "SELECT id, result, evaluation FROM causal_experiments "
            "WHERE user_id='creator' ORDER BY id"
        ).fetchall()
    ]
    review = review_causal_learning(db, "creator")
    after = [
        tuple(row) for row in db.execute(
            "SELECT id, result, evaluation FROM causal_experiments "
            "WHERE user_id='creator' ORDER BY id"
        ).fetchall()
    ]

    item = review["hypotheses"][0]
    assert item["evidence_assessment"] == "mixed_evidence"
    assert item["evidence_counts"] == {
        "supported": 1, "contradicted": 1, "inconclusive": 0,
    }
    assert [entry["evaluation"] for entry in item["evaluation_history"]] == [
        "contradicted", "supported",
    ]
    assert before == after
    assert review["read_only"] is True
    assert review["history_is_preserved"] is True
    db.close()


def test_inconclusive_result_is_not_mistaken_for_support_or_contradiction():
    db = make_db()
    hypothesis = make_hypothesis(db)
    complete_test(db, "creator", hypothesis["id"], "inconclusive",
                  "Le résultat n'est pas assez clair.")
    item = review_causal_learning(db, "creator")["hypotheses"][0]
    assert item["evidence_assessment"] == "inconclusive"
    assert item["evidence_counts"]["supported"] == 0
    assert item["evidence_counts"]["contradicted"] == 0
    db.close()


def test_review_is_user_scoped_and_does_not_expose_other_hypotheses():
    db = make_db()
    own = make_hypothesis(db, "alice")
    other = make_hypothesis(db, "bob")
    complete_test(db, "bob", other["id"], "contradicted",
                  "Résultat privé de bob.")
    review = review_causal_learning(db, "alice")
    assert [item["id"] for item in review["hypotheses"]] == [own["id"]]
    assert "Résultat privé de bob." not in str(review)
    assert review_causal_learning(db, "nobody")["hypotheses"] == []
    db.close()


def test_uncompleted_experiment_is_reported_as_awaiting_evaluation():
    db = make_db()
    hypothesis = make_hypothesis(db)
    plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "Simulation en attente", "La balle atteint le sol",
        supervisor_approved=True,
    )
    item = review_causal_learning(db, "creator")["hypotheses"][0]
    assert item["evidence_assessment"] == "awaiting_evaluation"
    assert item["evaluation_history"][0]["status"] == "planned"
    db.close()
