import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.causal_learning import (
    init_causal_learning_tables,
    record_observation,
    propose_hypothesis,
    plan_experiment,
    evaluate_experiment,
    list_causal_learning,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_causal_learning_tables(connection)
    yield connection
    connection.close()


def seed_hypothesis(db, user="creator"):
    observation = record_observation(
        db, user, "une balle tombe", "elle touche le sol",
        context="balle lâchée à faible hauteur",
        source_type="observed", confidence=0.8,
    )
    hypothesis = propose_hypothesis(
        db, user, observation["id"],
        "La balle tombe lorsqu'on la lâche",
        "elle atteint le sol", confidence=0.4,
    )
    return observation, hypothesis


def test_observation_keeps_provenance(db):
    observation, _ = seed_hypothesis(db)
    assert observation["source_type"] == "observed"
    assert observation["confidence"] == 0.8


def test_hypothesis_requires_existing_owned_observation(db):
    with pytest.raises(ValueError):
        propose_hypothesis(db, "creator", 999, "hypothèse", "effet")


def test_user_cannot_reference_another_users_observation(db):
    observation, _ = seed_hypothesis(db, "alice")
    with pytest.raises(ValueError):
        propose_hypothesis(db, "bob", observation["id"], "hypothèse", "effet")


def test_experiment_requires_explicit_supervisor_approval(db):
    _, hypothesis = seed_hypothesis(db)
    with pytest.raises(ValueError):
        plan_experiment(
            db, "creator", hypothesis["id"], "simulation",
            "lâcher une balle virtuelle", "elle tombe", False,
        )


def test_experiment_rejects_unsafe_environment(db):
    _, hypothesis = seed_hypothesis(db)
    with pytest.raises(ValueError):
        plan_experiment(
            db, "creator", hypothesis["id"], "real_world",
            "action non contrôlée", "résultat", True,
        )


def test_supervised_simulation_can_be_planned(db):
    _, hypothesis = seed_hypothesis(db)
    experiment = plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "lâcher une balle virtuelle", "elle touche le sol", True,
    )
    assert experiment["status"] == "planned"
    assert experiment["supervisor_approved"] is True


def test_supported_result_increases_confidence(db):
    _, hypothesis = seed_hypothesis(db)
    experiment = plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "test virtuel", "la balle tombe", True,
    )
    result = evaluate_experiment(
        db, "creator", experiment["id"], "la balle touche le sol", "supported"
    )
    assert result["confidence"] > result["previous_confidence"]
    assert result["status"] == "supported"


def test_contradicted_result_reduces_confidence(db):
    _, hypothesis = seed_hypothesis(db)
    experiment = plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "test virtuel", "la balle tombe", True,
    )
    result = evaluate_experiment(
        db, "creator", experiment["id"], "la balle est restée immobile", "contradicted"
    )
    assert result["confidence"] < result["previous_confidence"]
    assert result["status"] == "contradicted"


def test_inconclusive_result_does_not_change_confidence(db):
    _, hypothesis = seed_hypothesis(db)
    experiment = plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "test virtuel", "la balle tombe", True,
    )
    result = evaluate_experiment(
        db, "creator", experiment["id"], "résultat ambigu", "inconclusive"
    )
    assert result["confidence"] == result["previous_confidence"]
    assert result["status"] == "uncertain"


def test_experiment_cannot_be_evaluated_twice(db):
    _, hypothesis = seed_hypothesis(db)
    experiment = plan_experiment(
        db, "creator", hypothesis["id"], "simulation",
        "test virtuel", "la balle tombe", True,
    )
    first = evaluate_experiment(
        db, "creator", experiment["id"], "elle tombe", "supported"
    )
    with pytest.raises(ValueError):
        evaluate_experiment(db, "creator", experiment["id"], "elle tombe", "supported")

    hypothesis_row = db.execute(
        "SELECT confidence, evidence_count FROM causal_hypotheses WHERE id=?",
        (hypothesis["id"],),
    ).fetchone()
    experiment_row = db.execute(
        "SELECT status, evaluation FROM causal_experiments WHERE id=?",
        (experiment["id"],),
    ).fetchone()
    assert hypothesis_row["confidence"] == first["confidence"]
    assert hypothesis_row["evidence_count"] == 1
    assert experiment_row["status"] == "completed"
    assert experiment_row["evaluation"] == "supported"


def test_dashboard_is_scoped_to_user(db):
    seed_hypothesis(db, "alice")
    assert list_causal_learning(db, "bob") == {
        "observations": [], "hypotheses": [], "experiments": []
    }



@pytest.mark.parametrize("bad", [None, 7, True, {}, []])
def test_observation_rejects_non_text_evidence_without_writing(db, bad):
    with pytest.raises(ValueError):
        record_observation(db, "creator", "événement", "résultat", evidence=bad)
    assert db.execute("SELECT COUNT(*) FROM causal_observations").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [True, False])
def test_causal_confidence_rejects_boolean_values(db, bad):
    with pytest.raises(ValueError):
        record_observation(db, "creator", "événement", "résultat", confidence=bad)
    assert db.execute("SELECT COUNT(*) FROM causal_observations").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [None, "", "   ", 7, True, {}, []])
def test_causal_observation_rejects_invalid_user_identity(db, bad):
    with pytest.raises(ValueError):
        record_observation(db, bad, "événement", "résultat")
    assert db.execute("SELECT COUNT(*) FROM causal_observations").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "5", None])
def test_causal_review_rejects_invalid_limit(db, bad):
    from learning.causal_learning import review_causal_learning
    with pytest.raises(ValueError):
        review_causal_learning(db, "creator", limit=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "inf"])
def test_causal_confidence_rejects_non_finite_values_without_writing(db, bad):
    with pytest.raises(ValueError, match="finie"):
        record_observation(
            db, "creator", "événement", "résultat", confidence=bad
        )
    assert db.execute("SELECT COUNT(*) FROM causal_observations").fetchone()[0] == 0
