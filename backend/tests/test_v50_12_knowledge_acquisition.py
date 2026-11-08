"""V50.12 — provenance-aware knowledge retrieval and reuse."""
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from memory.knowledge_acquisition import (
    retrieve_acquired_knowledge, format_acquired_knowledge_context,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE memories_v19 (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, category TEXT,
            content TEXT, source_type TEXT, confidence REAL, importance INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE autobiographical_events (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, actor TEXT,
            event_type TEXT, content TEXT, happened_at TEXT,
            source_conversation_id INTEGER
        );
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, test_name TEXT,
            passed INTEGER, score REAL, details TEXT, tested_at TEXT
        );
    """)
    return db


def seed(db, user="creator"):
    db.execute(
        """INSERT INTO memories_v19 VALUES
           (1, ?, 'objets', 'Une montre possède un cadran rond',
            'taught', 0.8, 3, '2026-11-01', '2026-11-01')""", (user,)
    )
    db.execute(
        """INSERT INTO memories_v19 VALUES
           (2, ?, 'objets', 'Le cadran de cette montre a été confirmé',
            'confirmed', 0.95, 4, '2026-11-02', '2026-11-02')""", (user,)
    )
    db.execute(
        """INSERT INTO autobiographical_events VALUES
           (1, ?, 'user', 'user_statement',
            'Le Créateur a montré une montre à Chappie',
            '2026-11-03', 12)""", (user,)
    )
    details = {
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "A distingué correctement trois montres nouvelles.",
        "goal_id": 8,
        "goal_step_id": 11,
    }
    db.execute(
        """INSERT INTO competency_tests VALUES
           (1, ?, 'tete:reconnaissance_objets', 1, 88, ?, '2026-11-04')""",
        (user, json.dumps(details)),
    )
    db.commit()


def test_retrieval_preserves_provenance_and_never_promotes_experience():
    db = make_db()
    seed(db)
    result = retrieve_acquired_knowledge(db, "creator", "montre")
    statuses = {item["status"] for item in result["items"]}
    assert "taught_not_independently_verified" in statuses
    assert "confirmed_memory" in statuses
    assert "experience_only_not_proof_of_learning" in statuses
    assert "supervised_skill_validated" in statuses
    assert result["read_only"] is True
    db.close()


def test_supervised_skill_requires_pass_and_explicit_approval():
    db = make_db()
    seed(db)
    db.execute(
        """INSERT INTO competency_tests VALUES
           (2, 'creator', 'tete:vision', 1, 99,
            '{"source":"supervised_assessment","supervisor_approved":false}',
            '2026-11-05')"""
    )
    db.execute(
        """INSERT INTO competency_tests VALUES
           (3, 'creator', 'tete:audition', 0, 95,
            '{"source":"supervised_assessment","supervisor_approved":true}',
            '2026-11-06')"""
    )
    db.commit()
    items = retrieve_acquired_knowledge(db, "creator")["items"]
    by_skill = {item.get("skill"): item["status"] for item in items if item["kind"] == "skill_assessment"}
    assert by_skill["tete:reconnaissance_objets"] == "supervised_skill_validated"
    assert by_skill["tete:vision"] == "assessment_provenance_unconfirmed"
    assert by_skill["tete:audition"] == "supervised_assessment_not_validated"
    db.close()


def test_user_isolation_and_query_relevance():
    db = make_db()
    seed(db, "alice")
    db.execute(
        """INSERT INTO memories_v19 VALUES
           (3, 'bob', 'autre', 'Un avion vole dans le ciel',
            'confirmed', 1.0, 5, '2026-11-04', '2026-11-04')"""
    )
    db.commit()
    alice = retrieve_acquired_knowledge(db, "alice", "montre")
    bob = retrieve_acquired_knowledge(db, "bob", "montre")
    assert alice["items"]
    assert all("avion" not in item["content"] for item in alice["items"])
    assert bob["items"] == []
    db.close()


def test_retrieval_does_not_change_any_source_rows():
    db = make_db()
    seed(db)
    before = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("memories_v19", "autobiographical_events", "competency_tests")
    }
    retrieve_acquired_knowledge(db, "creator", "montre")
    after = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in before
    }
    assert before == after
    db.close()


def test_formatted_context_is_bounded_and_keeps_uncertainty_rules():
    db = make_db()
    seed(db)
    result = retrieve_acquired_knowledge(db, "creator", "montre")
    context = format_acquired_knowledge_context(result, max_chars=1000)
    assert len(context) <= 1000
    assert "expérience n'est pas une preuve" in context
    assert "observed_not_understood" in context
    db.close()


def test_missing_optional_tables_are_safe():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE memories_v19 (
            id INTEGER PRIMARY KEY, user_id TEXT, category TEXT, content TEXT,
            source_type TEXT, confidence REAL, importance INTEGER,
            created_at TEXT, updated_at TEXT
        )"""
    )
    db.execute(
        """INSERT INTO memories_v19 VALUES
           (1, 'creator', 'general', 'Un souvenir ancien',
            'inferred', 0.4, 2, '2026-01-01', '2026-01-01')"""
    )
    result = retrieve_acquired_knowledge(db, "creator")
    assert result["items"][0]["status"] == "hypothesis_unverified"
    db.close()


def test_server_exposes_retrieval_to_shared_chat_and_live_tools():
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "from memory.knowledge_acquisition import" in server
    assert '"name": "retrieve_acquired_knowledge"' in server
    assert 'if name == "retrieve_acquired_knowledge"' in server
    assert "{acquired_knowledge_context}" in server
    assert "get_identity_prompt(user_id)" in server
