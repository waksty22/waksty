"""V50.10 supervised personal learning goals: persistence and evidence safety."""
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from learning.causal_learning import (
    init_causal_learning_tables, record_observation, propose_hypothesis,
    plan_experiment, evaluate_experiment,
)
from learning.personal_goals import (
    suggest_personal_learning_goals, list_personal_learning_goals,
    record_personal_goal_step,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            progress REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE goal_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    init_causal_learning_tables(db)
    return db


def add_contradicted_hypothesis(db, user_id="creator"):
    observation = record_observation(db, user_id, "Une feuille change de couleur",
                                     "La feuille devient jaune")
    hypothesis = propose_hypothesis(db, user_id, observation["id"],
                                    "La lumière modifie la couleur", "La feuille jaunit")
    experiment = plan_experiment(db, user_id, hypothesis["id"], "simulation",
                                 "Simulation contrôlée", "La feuille jaunit", True)
    evaluate_experiment(db, user_id, experiment["id"], "La feuille reste verte",
                        "contradicted")


def test_suggestions_are_read_only_and_require_approval():
    db = make_db()
    add_contradicted_hypothesis(db)
    before = db.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
    result = suggest_personal_learning_goals(db, "creator")
    after = db.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
    assert result["proposals"]
    assert result["approval_required"] is True
    assert result["goals_created"] == 0
    assert result["proposals"][0]["persisted"] is False
    assert len(result["proposals"][0]["steps"]) == 3
    assert before == after == 0
    db.close()


def test_suggestions_are_scoped_to_user():
    db = make_db()
    add_contradicted_hypothesis(db, "alice")
    assert suggest_personal_learning_goals(db, "bob")["proposals"] == []
    db.close()


def test_active_duplicate_goal_is_not_proposed_twice():
    db = make_db()
    add_contradicted_hypothesis(db)
    proposal = suggest_personal_learning_goals(db, "creator")["proposals"][0]
    db.execute("INSERT INTO goals(user_id,title) VALUES(?,?)",
               ("creator", proposal["title"]))
    db.commit()
    result = suggest_personal_learning_goals(db, "creator")
    assert all(item["title"] != proposal["title"] for item in result["proposals"])
    db.close()


def test_goal_progress_requires_evidence_and_is_user_scoped():
    db = make_db()
    db.execute("INSERT INTO goals(user_id,title) VALUES('alice','Objectif')")
    goal_id = db.execute("SELECT id FROM goals").fetchone()["id"]
    db.execute("INSERT INTO goal_steps(goal_id,description) VALUES(?, 'Étape')")
    step_id = db.execute("SELECT id FROM goal_steps").fetchone()["id"]
    db.commit()
    try:
        record_personal_goal_step(db, "bob", goal_id, step_id, "preuve")
        assert False, "Un autre utilisateur ne doit pas pouvoir modifier l'objectif."
    except ValueError:
        pass
    try:
        record_personal_goal_step(db, "alice", goal_id, step_id, "   ")
        assert False, "Une preuve vide doit être refusée."
    except ValueError:
        pass
    result = record_personal_goal_step(db, "alice", goal_id, step_id, "Résultat vérifié")
    assert result["progress"] == 100.0
    assert result["goal_status"] == "completed"
    db.close()


def test_goal_listing_includes_steps_and_never_writes():
    db = make_db()
    db.execute("INSERT INTO goals(user_id,title) VALUES('creator','Objectif')")
    goal_id = db.execute("SELECT id FROM goals").fetchone()["id"]
    db.execute("INSERT INTO goal_steps(goal_id,description) VALUES(?, 'Étape mesurable')",
               (goal_id,))
    db.commit()
    result = list_personal_learning_goals(db, "creator")
    assert len(result["goals"]) == 1
    assert result["goals"][0]["steps"][0]["description"] == "Étape mesurable"
    assert result["read_only"] is True
    db.close()
