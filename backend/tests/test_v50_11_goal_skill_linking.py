"""V50.11 links completed goal steps to supervisor-validated cognitive skills."""
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.skill_evidence import build_validated_skill_data
from learning.personal_goals import list_personal_learning_goals, list_goal_skill_assessments

SERVER = (BACKEND / "server.py").read_text(encoding="utf-8")
APP = (BACKEND / "static" / "js" / "app.js").read_text(encoding="utf-8")


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
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, test_name TEXT NOT NULL,
            passed INTEGER NOT NULL, score REAL NOT NULL,
            details TEXT NOT NULL DEFAULT '{}', tested_at TEXT NOT NULL
        );
    """)
    return db


def seed_goal(db, user="creator"):
    cur = db.execute("INSERT INTO goals(user_id,title) VALUES(?,?)", (user, "Comprendre une observation"))
    goal_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO goal_steps(goal_id,description,status,evidence) VALUES(?,?,'completed',?)",
        (goal_id, "Décrire ce qui est observé", "Observation vérifiée sur trois essais distincts."),
    )
    db.commit()
    return goal_id, cur.lastrowid


def test_only_linked_supervised_assessments_are_listed_for_the_goal_owner():
    db = make_db()
    goal_id, step_id = seed_goal(db)
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Chappie a distingué correctement trois résultats nouveaux.",
        "goal_id": goal_id,
        "goal_step_id": step_id,
    }
    db.execute(
        "INSERT INTO competency_tests(user_id,test_name,passed,score,details,tested_at) VALUES(?,?,?,?,?,?)",
        ("creator", "tete:logique_inductive", 1, 85, json.dumps(details), "2026-11-08T10:00:00Z"),
    )
    db.execute(
        "INSERT INTO competency_tests(user_id,test_name,passed,score,details,tested_at) VALUES(?,?,?,?,?,?)",
        ("creator", "tete:logique_formelle", 1, 90, json.dumps({
            **details, "supervisor_approved": False, "goal_id": goal_id
        }), "2026-11-08T10:01:00Z"),
    )
    db.commit()
    linked = list_goal_skill_assessments(db, "creator", goal_id)
    assert len(linked) == 1
    assert linked[0]["test_name"] == "tete:logique_inductive"
    assert linked[0]["goal_step_id"] == step_id
    goals = list_personal_learning_goals(db, "creator")
    assert goals["goals"][0]["skill_assessments"] == linked
    db.close()


def test_linked_assessment_is_real_input_to_validated_skill_profile():
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Résolution correcte de quatre situations nouvelles et contrôlées.",
        "goal_id": 17,
        "goal_step_id": 29,
    }
    profile, count = build_validated_skill_data([{
        "test_name": "tete:raisonnement_causal",
        "passed": 1,
        "score": 90,
        "tested_at": "2026-11-08T10:00:00Z",
        "details": details,
    }])
    assert count == 1
    assert profile["tete"]["raisonnement_causal"]["level"] == 9
    assert profile["tete"]["raisonnement_causal"]["confidence"] == 1 / 3


def test_linked_assessment_api_requires_owned_completed_step_with_evidence():
    assert "goal_id = data.get(\"goal_id\")" in SERVER
    assert "goal_step_id = data.get(\"goal_step_id\")" in SERVER
    assert "g.user_id=? AND s.id=?" in SERVER
    assert "s.status='completed' AND length(trim(s.evidence))>0" in SERVER
    assert 'details["goal_id"] = goal_id' in SERVER
    assert 'details["goal_step_id"] = goal_step_id' in SERVER


def test_dashboard_links_goal_step_to_supervised_assessment_and_refreshes_tree():
    assert 'goal.skill_assessments || []' in APP
    assert 'goal_id: goal.id' in APP
    assert 'goal_step_id: Number(stepSelect.value)' in APP
    assert 'supervisor_approved: true' in APP
    assert 'await window.loadSkills();' in APP
    assert "Valider l'évaluation de compétence" in APP


def test_goal_skill_assessment_lookup_rejects_another_users_goal():
    db = make_db()
    goal_id, _ = seed_goal(db, "alice")
    try:
        list_goal_skill_assessments(db, "bob", goal_id)
        assert False, "La lecture des évaluations doit respecter le propriétaire."
    except ValueError:
        pass
    db.close()



def test_supervised_assessment_route_rejects_coerced_payload_values():
    route = SERVER.split('@app.post("/api/cognition/skills/assessments")', 1)[1].split('@app.post("/api/skills/update")', 1)[0]
    assert 'system_value = data.get("system", "")' in route
    assert 'branch_value = data.get("branch", "")' in route
    assert 'evidence_value = data.get("evidence", "")' in route
    assert "all(isinstance(value, str)" in route
    assert 'raw_score = data.get("score")' in route
    assert 'not isinstance(raw_score, (int, float))' in route
    assert 'isinstance(raw_score, bool)' in route
    assert "goal_id = int(goal_id)" not in route
    assert "goal_step_id = int(goal_step_id)" not in route
    assert "isinstance(goal_id, bool)" in route
    assert "isinstance(goal_step_id, bool)" in route


def test_skill_profile_rejects_coerced_scores_pass_flags_and_evidence():
    valid_details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Résolution vérifiée sur plusieurs situations distinctes.",
    }
    base = {
        "test_name": "tete:raisonnement_causal",
        "passed": 1,
        "score": 90,
        "tested_at": "2026-11-15T12:00:00Z",
        "details": valid_details,
    }
    invalid_rows = []
    for field, values in {
        "test_name": [7, True, None, "tete", "tete:raisonnement_causal:extra"],
        "score": ["90", True, None, {}, [], float("nan"), float("inf")],
        "passed": [True, "1", 0, None],
        "tested_at": [7, None, {}],
    }.items():
        for value in values:
            invalid_rows.append({**base, field: value})
    missing_pass_flag = dict(base)
    missing_pass_flag.pop("passed")
    invalid_rows.append(missing_pass_flag)
    for value in (None, 7, True, {}, [], "trop court"):
        invalid_rows.append({
            **base,
            "details": {**valid_details, "evidence": value},
        })

    for row in invalid_rows:
        profile, count = build_validated_skill_data([row])
        assert count == 0, f"Une preuve invalide a été acceptée: {row!r}"
        assert profile == {}


def test_skill_profile_accepts_valid_json_details_but_deduplicates_evidence():
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Résolution vérifiée sur plusieurs situations distinctes.",
    }
    row = {
        "test_name": "tete:raisonnement_causal",
        "passed": 1,
        "score": 90,
        "tested_at": "2026-11-15T12:00:00Z",
        "details": json.dumps(details),
    }
    profile, count = build_validated_skill_data([row, row])
    assert count == 1
    assert profile["tete"]["raisonnement_causal"]["confidence"] == 1 / 3


def test_assessment_duplicate_guard_ignores_non_object_historical_details():
    route = SERVER.split('@app.post("/api/cognition/skills/assessments")', 1)[1].split('@app.post("/api/skills/update")', 1)[0]
    assert 'old_details = json.loads(row["details"] or "{}")' in route
    assert "if not isinstance(old_details, dict):" in route
    assert 'old_details.get("evidence") == evidence' in route
