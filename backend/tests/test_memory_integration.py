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
