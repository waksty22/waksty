"""V50.8 — read-only supervised learning agenda and explicit approval gates."""
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
    suggest_supervised_learning_agenda,
    format_supervised_learning_agenda,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_causal_learning_tables(db)
    return db


def add_hypothesis(db, user_id="creator"):
    observation = record_observation(
        db, user_id, "Une feuille change de couleur",
        "La feuille devient jaune", source_type="observed",
    )
    hypothesis = propose_hypothesis(
        db, user_id, observation["id"],
        "Cette feuille jaunit dans ces conditions",
        "La feuille devient jaune", confidence=0.5,
    )
    return observation, hypothesis


def add_evaluation(db, user_id, hypothesis_id, evaluation, result):
    experiment = plan_experiment(
        db, user_id, hypothesis_id, "simulation",
        "Simulation limitée", "La feuille devient jaune",
        supervisor_approved=True,
    )
    evaluate_experiment(db, user_id, experiment["id"], result, evaluation)


def test_agenda_prioritizes_contradicted_hypothesis_without_creating_experiment():
    db = make_db()
    _, hypothesis = add_hypothesis(db)
    add_evaluation(db, "creator", hypothesis["id"], "contradicted", "La feuille reste verte.")
    before = db.execute("SELECT COUNT(*) FROM causal_experiments").fetchone()[0]
    agenda = suggest_supervised_learning_agenda(db, "creator")
    after = db.execute("SELECT COUNT(*) FROM causal_experiments").fetchone()[0]
    item = agenda["agenda"][0]
    assert item["kind"] == "review_hypothesis"
    assert item["priority"] == "high"
    assert item["requires_supervisor_approval"] is True
    assert item["no_experiment_created"] is True
    assert before == after
    assert agenda["experiments_created"] == 0
    assert agenda["autonomous_execution"] is False
    db.close()


def test_unlinked_observation_becomes_a_low_priority_question_not_a_fact():
    db = make_db()
    record_observation(
        db, "creator", "Un bruit est entendu",
        "Origine inconnue", source_type="observed",
    )
    agenda = suggest_supervised_learning_agenda(db, "creator")
    item = agenda["agenda"][0]
    assert item["kind"] == "observation_to_understand"
    assert item["priority"] == "low"
    assert "ne rien déduire automatiquement" in item["suggested_next_step"]
    db.close()


def test_pending_experiment_is_not_duplicated_in_agenda():
    db = make_db()
    _, hypothesis = add_hypothesis(db)
    plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "Simulation en cours", "La feuille devient jaune",
        supervisor_approved=True,
    )
    agenda = suggest_supervised_learning_agenda(db, "creator")
    assert all(item["source_id"] != hypothesis["id"] for item in agenda["agenda"])
    db.close()


def test_agenda_is_isolated_by_user():
    db = make_db()
    _, hypothesis = add_hypothesis(db, "alice")
    add_evaluation(db, "alice", hypothesis["id"], "contradicted", "Privé Alice.")
    record_observation(db, "bob", "Observation Bob", "Résultat Bob", source_type="observed")
    alice = suggest_supervised_learning_agenda(db, "alice")
    assert all("Bob" not in str(item) for item in alice["agenda"])
    assert all(item["kind"] == "review_hypothesis" for item in alice["agenda"])
    db.close()


def test_agenda_context_is_bounded_and_states_supervision_requirement():
    db = make_db()
    record_observation(db, "creator", "Un son est entendu", "Non identifié")
    context = format_supervised_learning_agenda(db, "creator", max_chars=900)
    assert len(context) <= 900
    assert "approbation explicite" in context
    assert "Tu ne crées, ne planifies et n'exécutes aucune expérience" in context
    db.close()
