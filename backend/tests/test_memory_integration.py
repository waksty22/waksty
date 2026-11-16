import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.episodic_memory import init_memory_tables, migrate_legacy_memories
from cognition.shared_brain import get_shared_brain_snapshot


def test_legacy_memories_are_migrated_and_read_by_shared_brain():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL,
            content TEXT NOT NULL, importance INTEGER NOT NULL, tags TEXT NOT NULL,
            access_count INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        )
    """)
    db.execute(
        "INSERT INTO memories VALUES (1,'creator','general','Souvenir historique',4,?,2,'t0','t1')",
        (json.dumps(["ancien"]),),
    )
    init_memory_tables(db)
    assert migrate_legacy_memories(db) == 0
    snapshot = get_shared_brain_snapshot(db, "creator")
    memory = snapshot["memories"][0]
    assert memory["content"] == "Souvenir historique"
    assert memory["source_type"] == "inferred"
    assert memory["confidence"] == 0.5
    assert "legacy_source_unverified" in memory["tags"]
    assert snapshot["statistics"]["totals"]["memories"] == 1
    db.close()


def test_memory_migration_is_idempotent_and_preserves_legacy_data():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, category TEXT NOT NULL,
            content TEXT NOT NULL, importance INTEGER NOT NULL, tags TEXT NOT NULL,
            access_count INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        )
    """)
    db.execute(
        "INSERT INTO memories VALUES (1,'creator','general','À conserver',5,'[]',7,'t0','t1')"
    )
    init_memory_tables(db)
    assert db.execute("SELECT COUNT(*) FROM memories_v19").fetchone()[0] == 1
    assert migrate_legacy_memories(db) == 0
    assert db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    assert db.execute("SELECT access_count FROM memories_v19").fetchone()[0] == 7
    db.close()

def test_retrieval_matches_multiple_query_terms_and_ranks_relevance_first():
    from memory.episodic_memory import save_episodic_memory, search_episodic_memories

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    save_episodic_memory(
        db, "creator", "La maison bleue près du port",
        category="famille", importance=2, tags=["Bretagne"],
    )
    save_episodic_memory(
        db, "creator", "Le port de pêche",
        category="lieu", importance=5, tags=["bateau"],
    )
    db.commit()

    results = search_episodic_memories(db, "creator", "maison port", limit=5)
    assert [item["content"] for item in results] == [
        "La maison bleue près du port",
        "Le port de pêche",
    ]
    assert results[0]["relevance_score"] > results[1]["relevance_score"]
    assert db.execute(
        "SELECT access_count FROM memories_v19 WHERE content=?",
        ("La maison bleue près du port",),
    ).fetchone()[0] == 1
    db.close()


def test_retrieval_is_accent_insensitive_and_keeps_user_isolation():
    from memory.episodic_memory import save_episodic_memory, search_episodic_memories

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    save_episodic_memory(
        db, "creator", "Le café préféré est près de la gare",
        category="préférence", importance=3,
    )
    save_episodic_memory(
        db, "another-user", "Le cafe préféré est près de la gare",
        category="préférence", importance=5,
    )
    db.commit()

    results = search_episodic_memories(db, "creator", "cafe gare", limit=5)
    assert len(results) == 1
    assert results[0]["user_id"] == "creator"
    assert results[0]["content"] == "Le café préféré est près de la gare"
    assert search_episodic_memories(db, "creator", "inexistant", limit=5) == []
    db.close()



def test_knowledge_retrieval_requires_strict_supervised_passing_evidence():
    from memory.knowledge_acquisition import retrieve_acquired_knowledge

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE competency_tests (
            id INTEGER PRIMARY KEY, user_id TEXT, test_name TEXT,
            passed, score, details TEXT, tested_at TEXT
        )
    """)
    details = json.dumps({
        "source": "supervised_assessment",
        "supervisor_approved": True,
        "evidence": "Raisonnement vérifié sur plusieurs exercices distincts.",
    })
    rows = [
        (1, "creator", "tete:raisonnement", 1, 90, details, "t1"),
        (2, "creator", "tete:raisonnement", "1", 90, details, "t2"),
        (3, "creator", "tete:raisonnement", True, 99, details, "t3"),
        (4, "creator", "tete:raisonnement", 0, 99, details, "t4"),
        (5, "creator", "tete:raisonnement", 1, "99", details, "t5"),
    ]
    db.executemany(
        "INSERT INTO competency_tests VALUES (?, ?, ?, ?, ?, ?, ?)", rows
    )
    result = retrieve_acquired_knowledge(
        db, "creator", query="raisonnement", limit=10
    )
    statuses = {
        item["source_id"]: item["status"]
        for item in result["items"]
        if item["kind"] == "skill_assessment"
    }
    assert statuses[1] == "supervised_skill_validated"
    assert statuses[2] == "supervised_assessment_not_validated"
    # SQLite stores Python bool values as INTEGER 1, so the retrieved row is
    # indistinguishable from an explicitly stored integer pass flag.
    assert statuses[3] == "supervised_skill_validated"
    assert statuses[4] == "supervised_assessment_not_validated"
    assert statuses[5] == "supervised_assessment_not_validated"
    from memory.knowledge_acquisition import _validated_assessment
    assert not _validated_assessment(json.loads(details), True, 99)
    assert result["read_only"] is True
    assert db.execute("SELECT COUNT(*) FROM competency_tests").fetchone()[0] == 5
    db.close()
