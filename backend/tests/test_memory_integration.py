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




def test_retrieval_uses_complete_tokens_not_substrings():
    from memory.episodic_memory import save_episodic_memory, search_episodic_memories

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    save_episodic_memory(
        db, "creator", "Un partage important avec la famille",
        category="general", importance=5,
    )
    save_episodic_memory(
        db, "creator", "L'art est un sujet différent",
        category="general", importance=2,
    )
    db.commit()

    results = search_episodic_memories(db, "creator", "art", limit=5)
    assert [item["content"] for item in results] == [
        "L'art est un sujet différent"
    ]
    db.close()


def test_retrieval_phrase_bonus_requires_complete_token_sequence():
    from memory.episodic_memory import save_episodic_memory, search_episodic_memories

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    save_episodic_memory(db, "creator", "Le partage est important", importance=5)
    save_episodic_memory(db, "creator", "Le sujet art est important", importance=2)
    db.commit()

    results = search_episodic_memories(db, "creator", "art est", limit=5)
    assert [item["content"] for item in results] == ["Le sujet art est important"]
    db.close()
