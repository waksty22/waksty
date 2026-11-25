"""Query-aware recall of older episodic and supervised cognitive records."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.development import init_development_tables
from cognition.shared_brain import get_shared_brain_snapshot
from learning.causal_learning import init_causal_learning_tables
from learning.object_learning import init_object_learning_tables
from learning.supervised_learning import init_supervised_learning_tables
from memory.episodic_memory import init_memory_tables
from world.world_model import init_world_tables


def test_query_ranks_older_records_across_cognitive_domains():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_world_tables(db)
    init_memory_tables(db)
    init_object_learning_tables(db)
    init_causal_learning_tables(db)
    init_supervised_learning_tables(db)
    init_development_tables(db)
    db.executescript("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0.0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, skill_name)
        );
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            test_name TEXT NOT NULL,
            passed INTEGER NOT NULL,
            score REAL NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            tested_at TEXT NOT NULL
        );
    """)

    # Emotional episodes are historical evidence, not a current state.
    db.execute(
        """INSERT INTO affective_history
           (user_id,source,event_label,state_json,created_at)
           VALUES ('creator','conversation','réaction à la panne du robot',
                   '{"curiosity":85,"frustration":20}','2025-01-01')"""
    )
    for index in range(5):
        db.execute(
            """INSERT INTO affective_history
               (user_id,source,event_label,state_json,created_at)
               VALUES ('creator','conversation',?,'{"curiosity":10}',?)""",
            (f"interaction neutre {index}", f"2026-01-0{index+1}"),
        )

    # Old but relevant records must outrank several newer unrelated records.
    db.execute(
        """INSERT INTO memories_v19
           (user_id,category,content,importance,source_type,confidence,tags,
            access_count,created_at,updated_at)
           VALUES ('creator','objet','Le vélo rouge était dans le garage',2,
                   'taught',0.8,'["mobilité"]',0,'2025-01-01','2025-01-01')"""
    )
    for index in range(5):
        db.execute(
            """INSERT INTO memories_v19
               (user_id,category,content,importance,source_type,confidence,tags,
                access_count,created_at,updated_at)
               VALUES ('creator','general',?,5,'taught',0.8,'[]',0,?,?)""",
            (f"souvenir récent {index}", f"2026-01-0{index+1}", f"2026-01-0{index+1}"),
        )

    db.execute(
        """INSERT INTO causal_observations
           (user_id,event,context,outcome,source_type,evidence,confidence,created_at)
           VALUES ('creator','Le vélo rouge tombe','sol lisse','chute',
                   'observed','observation ancienne',0.7,'2025-01-01')"""
    )
    for index in range(4):
        db.execute(
            """INSERT INTO causal_observations
               (user_id,event,context,outcome,source_type,evidence,confidence,created_at)
               VALUES ('creator',?,?,?,'observed','neutre',0.5,?)""",
            (f"événement récent {index}", "contexte neutre", "résultat neutre", f"2026-01-0{index+1}"),
        )

    db.execute(
        """INSERT INTO imitation_examples
           (user_id,behavior,context,source_type,evidence,status,
            supervisor_approved,created_at,updated_at)
           VALUES ('creator','Réparer le vélo rouge','atelier',
                   'demonstrated','démonstration ancienne','observed',0,
                   '2025-01-01','2025-01-01')"""
    )
    for index in range(4):
        db.execute(
            """INSERT INTO imitation_examples
               (user_id,behavior,context,source_type,evidence,status,
                supervisor_approved,created_at,updated_at)
               VALUES ('creator',?,'contexte','demonstrated','neutre',
                       'observed',0,?,?)""",
            (f"action récente {index}", f"2026-01-0{index+1}", f"2026-01-0{index+1}"),
        )

    db.execute(
        """INSERT INTO decision_journal
           (user_id,question,options_json,chosen_option,reasons,evidence_json,
            confidence,outcome,status,created_at,updated_at)
           VALUES ('creator','Que faire du vélo rouge ?','[]','','choix ancien',
                   '[]',0.6,'','considered','2025-01-01','2025-01-01')"""
    )
    db.execute(
        """INSERT INTO preference_evidence
           (user_id,domain,preference,evidence,basis,confidence,created_at)
           VALUES ('creator','transport','vélo rouge','choix explicite',
                   'explicit_statement',0.9,'2025-01-01')"""
    )

    db.execute(
        """INSERT INTO skills (user_id,skill_name,level,evidence,updated_at)
           VALUES ('creator','navigation spatiale',0.2,'repérage ancien du robot','2025-01-01')"""
    )
    for index in range(4):
        db.execute(
            """INSERT INTO skills (user_id,skill_name,level,evidence,updated_at)
               VALUES ('creator',?,0.9,'preuve récente',?)""",
            (f"compétence récente {index}", f"2026-01-0{index+1}"),
        )
    db.execute(
        """INSERT INTO competency_tests
           (user_id,test_name,passed,score,details,tested_at)
           VALUES ('creator','robot:navigation',1,72,'test ancien de navigation spatiale','2025-01-01')"""
    )
    for index in range(4):
        db.execute(
            """INSERT INTO competency_tests
               (user_id,test_name,passed,score,details,tested_at)
               VALUES ('creator',?,1,99,'test sans rapport',?)""",
            (f"recent:other-{index}", f"2026-01-0{index+1}"),
        )

    snapshot = get_shared_brain_snapshot(db, "creator", limit=3, query="vélo rouge")

    assert "vélo rouge" in snapshot["memories"][0]["content"]
    assert "vélo rouge" in snapshot["causal_observations"][0]["event"]
    assert "vélo rouge" in snapshot["imitation_examples"][0]["behavior"]
    assert "vélo rouge" in snapshot["decision_journal"][0]["question"]
    assert "vélo rouge" in snapshot["preference_evidence"][0]["preference"]
    affective_snapshot = get_shared_brain_snapshot(
        db, "creator", limit=2, query="panne robot"
    )
    assert affective_snapshot["affective_history"][0]["event_label"] == (
        "réaction à la panne du robot"
    )
    assert json.loads(affective_snapshot["affective_history"][0]["state_json"])["curiosity"] == 85

    skill_snapshot = get_shared_brain_snapshot(
        db, "creator", limit=2, query="navigation spatiale"
    )
    assert skill_snapshot["skills"][0]["skill_name"] == "navigation spatiale"
    assert skill_snapshot["competency_tests"][0]["test_name"] == "robot:navigation"

    # Query-ranked results remain scoped to the requesting user.
    db.execute(
        """INSERT INTO memories_v19
           (user_id,category,content,importance,source_type,confidence,tags,
            access_count,created_at,updated_at)
           VALUES ('another-user','objet','vélo rouge secret',5,'taught',
                   0.9,'[]',0,'2026-01-01','2026-01-01')"""
    )
    other = get_shared_brain_snapshot(db, "another-user", limit=3, query="vélo rouge")
    assert other["memories"][0]["content"] == "vélo rouge secret"
    assert all("secret" not in row["content"] for row in snapshot["memories"])
    db.close()
