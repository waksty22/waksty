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
SERVER = (BACKEND / "server.py").read_text(encoding="utf-8")

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
    db.execute("INSERT INTO goal_steps(goal_id,description) VALUES(?, 'Étape')", (goal_id,))
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



def test_shared_brain_tools_and_authenticated_api_are_connected():
    assert '"name": "suggest_personal_learning_goals"' in SERVER
    assert '"name": "review_personal_learning_goals"' in SERVER
    assert 'if name == "suggest_personal_learning_goals"' in SERVER
    assert '@app.get("/api/learning/goals")' in SERVER
    assert '@app.post("/api/learning/goals/steps")' in SERVER
    assert "result = create_goal(" in SERVER
    assert "result = await create_goal(" not in SERVER


def test_dashboard_requires_click_to_adopt_and_evidence_to_progress():
    html = (BACKEND / "static" / "index.html").read_text(encoding="utf-8")
    app = (BACKEND / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="personalGoalProposals"' in html
    assert 'id="personalGoalsList"' in html
    assert 'textContent = "Adopter cet objectif"' in app
    assert 'apiCall("/api/goals"' in app
    assert 'apiCall("/api/learning/goals/steps"' in app
    assert 'evidence: evidence.value.trim()' in app



def test_personal_goal_suggestions_reject_invalid_user_and_limit():
    db = make_db()
    for bad_user in (None, "", "   ", 7, True, {}, []):
        try:
            suggest_personal_learning_goals(db, bad_user)
            assert False, "Identité invalide acceptée"
        except ValueError:
            pass
    for bad_limit in (0, -1, True, 1.5, "5", None):
        try:
            suggest_personal_learning_goals(db, "creator", limit=bad_limit)
            assert False, "Limite invalide acceptée"
        except ValueError:
            pass
    db.close()


def test_personal_goal_listing_rejects_invalid_user_and_limit():
    db = make_db()
    for bad_user in (None, "", "   ", 7, True, {}, []):
        try:
            list_personal_learning_goals(db, bad_user)
            assert False, "Identité invalide acceptée"
        except ValueError:
            pass
    for bad_limit in (0, -1, True, 1.5, "30", None):
        try:
            list_personal_learning_goals(db, "creator", limit=bad_limit)
            assert False, "Limite invalide acceptée"
        except ValueError:
            pass
    db.close()


def test_personal_goal_step_rejects_invalid_identifiers_without_writing():
    db = make_db()
    db.execute("INSERT INTO goals(user_id,title) VALUES('creator','Objectif')")
    goal_id = db.execute("SELECT id FROM goals").fetchone()["id"]
    db.execute("INSERT INTO goal_steps(goal_id,description) VALUES(?, 'Étape')", (goal_id,))
    step_id = db.execute("SELECT id FROM goal_steps").fetchone()["id"]
    db.commit()
    for bad_goal in (0, -1, True, 1.5, "1", None):
        try:
            record_personal_goal_step(db, "creator", bad_goal, step_id, "preuve")
            assert False, "Identifiant d'objectif invalide accepté"
        except ValueError:
            pass
    for bad_step in (0, -1, True, 1.5, "1", None):
        try:
            record_personal_goal_step(db, "creator", goal_id, bad_step, "preuve")
            assert False, "Identifiant d'étape invalide accepté"
        except ValueError:
            pass
    assert db.execute("SELECT status FROM goal_steps").fetchone()["status"] == "pending"
    db.close()


def test_supervised_goal_assessments_require_strict_integer_goal_linkage():
    import json
    from learning.personal_goals import list_goal_skill_assessments

    db = make_db()
    db.execute("INSERT INTO goals(user_id,title) VALUES('creator','Objectif')")
    goal_id = db.execute("SELECT id FROM goals").fetchone()["id"]
    db.execute(
        "INSERT INTO goal_steps(goal_id,description,status,evidence) VALUES(?,?,?,?)",
        (goal_id, "Étape", "completed", "Preuve documentée"),
    )
    step_id = db.execute("SELECT id FROM goal_steps").fetchone()["id"]
    db.execute("""
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            test_name TEXT,
            passed,
            score,
            tested_at,
            details TEXT
        )
    """)
    def details(linked_goal_id):
        return json.dumps({
            "goal_id": linked_goal_id,
            "goal_step_id": step_id,
            "source": "supervised_assessment",
            "supervisor_approved": True,
            "evidence": "Évaluation supervisée et preuve vérifiable.",
        })
    rows = [
        ("creator", "memory:recall", 1, 90, "2026-11-24", details(True)),
        ("creator", "memory:recall", 1, 90, "2026-11-24", details(1.0)),
        ("creator", "memory:recall", 1, 90, "2026-11-24", details("1")),
        ("creator", "memory:recall", 1, 90, "2026-11-24", details(goal_id)),
    ]
    db.executemany(
        "INSERT INTO competency_tests(user_id,test_name,passed,score,tested_at,details) VALUES(?,?,?,?,?,?)",
        rows,
    )
    db.commit()

    assessments = list_goal_skill_assessments(db, "creator", goal_id)
    assert len(assessments) == 1
    assert assessments[0]["test_name"] == "memory:recall"
    assert assessments[0]["score"] == 90.0
    db.close()


def test_supervised_goal_assessment_rejects_untyped_timestamp():
    import json
    from learning.personal_goals import list_goal_skill_assessments

    db = make_db()
    db.execute("INSERT INTO goals(user_id,title) VALUES('creator','Objectif')")
    goal_id = db.execute("SELECT id FROM goals").fetchone()["id"]
    db.execute(
        "INSERT INTO goal_steps(goal_id,description,status,evidence) VALUES(?,?,?,?)",
        (goal_id, "Étape", "completed", "Preuve documentée"),
    )
    step_id = db.execute("SELECT id FROM goal_steps").fetchone()["id"]
    db.execute("""
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            test_name TEXT,
            passed,
            score,
            tested_at,
            details TEXT
        )
    """)
    details = json.dumps({
        "goal_id": goal_id,
        "goal_step_id": step_id,
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Évaluation supervisée et preuve vérifiable.",
    })
    db.execute(
        "INSERT INTO competency_tests(user_id,test_name,passed,score,tested_at,details) VALUES(?,?,?,?,?,?)",
        ("creator", "memory:recall", 1, 90, None, details),
    )
    db.commit()
    assert list_goal_skill_assessments(db, "creator", goal_id) == []
    db.close()
