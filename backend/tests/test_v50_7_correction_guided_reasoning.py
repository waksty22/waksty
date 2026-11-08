"""V50.7 — historical corrections guide the shared chat/Live identity prompt."""
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
    format_causal_learning_guidance,
)


def setup_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_causal_learning_tables(db)
    return db


def create_test(db, user_id, evaluation, result):
    observation = record_observation(
        db, user_id, "Une graine est placée dans la terre",
        "Une pousse apparaît", source_type="observed",
    )
    hypothesis = propose_hypothesis(
        db, user_id, observation["id"],
        "Cette graine germe dans ces conditions",
        "Une pousse apparaît", confidence=0.6,
    )
    experiment = plan_experiment(
        db, user_id, hypothesis["id"], "simulation",
        "Simulation de germination", "Une pousse apparaît",
        supervisor_approved=True,
    )
    evaluate_experiment(db, user_id, experiment["id"], result, evaluation)


def test_guidance_includes_relevant_correction_and_mixed_evidence():
    db = setup_db()
    create_test(db, "creator", "contradicted", "Aucune pousse observée.")
    create_test(db, "creator", "supported", "Une pousse observée.")
    context = format_causal_learning_guidance(db, "creator")
    assert "bilan=mixed_evidence" in context
    assert "contredites=1" in context
    assert "étayées=1" in context
    assert "Aucune pousse observée." in context
    assert "Une pousse observée." in context
    db.close()


def test_guidance_is_user_scoped():
    db = setup_db()
    create_test(db, "alice", "contradicted", "Résultat privé Alice.")
    create_test(db, "bob", "supported", "Résultat privé Bob.")
    alice = format_causal_learning_guidance(db, "alice")
    assert "Résultat privé Alice." in alice
    assert "Résultat privé Bob." not in alice
    db.close()


def test_guidance_keeps_inconclusive_separate_and_is_bounded():
    db = setup_db()
    create_test(db, "creator", "inconclusive", "Mesure insuffisante.")
    context = format_causal_learning_guidance(db, "creator", max_chars=900)
    assert "bilan=inconclusive" in context
    assert "non concluantes=1" in context
    assert len(context) <= 900
    db.close()


def test_empty_history_explains_no_evaluated_experiments():
    db = setup_db()
    context = format_causal_learning_guidance(db, "creator")
    assert "Aucune expérience évaluée" in context
    db.close()
