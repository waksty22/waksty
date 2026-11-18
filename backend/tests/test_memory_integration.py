import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.episodic_memory import init_memory_tables, migrate_legacy_memories, search_episodic_memories
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



def test_knowledge_retrieval_rejects_coerced_limits_and_handles_bad_confidence():
    from memory.knowledge_acquisition import retrieve_acquired_knowledge

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE memories_v19 (
            id INTEGER PRIMARY KEY, user_id TEXT, category TEXT, content TEXT,
            source_type TEXT, confidence, importance INTEGER,
            created_at TEXT, updated_at TEXT
        )
    """)
    db.execute(
        "INSERT INTO memories_v19 VALUES (1,'creator','general','souvenir','confirmed','bad',3,'t0','t1')"
    )
    for invalid_limit in (True, False, 1.5, "3", None):
        try:
            retrieve_acquired_knowledge(db, "creator", limit=invalid_limit)
        except ValueError:
            pass
        else:
            raise AssertionError(f"limit should be rejected: {invalid_limit!r}")

    result = retrieve_acquired_knowledge(db, " creator ", query="souvenir")
    assert result["items"][0]["confidence"] == 0.0
    db.close()



def test_episodic_memory_rejects_coerced_provenance_tags_and_numbers():
    from memory.episodic_memory import (
        _normalize_confidence, _normalize_importance, _normalize_limit,
        _normalize_source_type, _normalize_tags, init_memory_tables,
        save_episodic_memory,
    )

    invalid_sources = (1, True, [], {}, "unknown")
    for value in invalid_sources:
        try:
            _normalize_source_type(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"source type should be rejected: {value!r}")

    for value in (("tag",), ["tag", 3], ["tag", None], {"tag": "value"}):
        try:
            _normalize_tags(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"tags should be rejected: {value!r}")

    for value in (True, False, 1.5, "4", None):
        for normalizer in (_normalize_importance, _normalize_limit):
            try:
                normalizer(value) if normalizer is _normalize_importance else normalizer(value, 1, 30)
            except ValueError:
                pass
            else:
                raise AssertionError(f"numeric input should be rejected: {value!r}")

    for value in (True, "0.8", [], None):
        try:
            _normalize_confidence(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"confidence should be rejected: {value!r}")

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    for kwargs in (
        {"source_type": 1}, {"tags": ["ok", 2]}, {"importance": 3.5},
        {"confidence": "0.9"},
    ):
        try:
            save_episodic_memory(db, "creator", "souvenir invalide", **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"save should reject invalid arguments: {kwargs!r}")
    assert db.execute("SELECT COUNT(*) FROM memories_v19").fetchone()[0] == 0
    db.close()



def test_legacy_memory_migration_ignores_malformed_non_text_tags():
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
        "INSERT INTO memories VALUES (1,'creator','general','Souvenir tags corrompus',3,?,0,'t0','t1')",
        (json.dumps(["valide", 42, None, {"tag": "objet"}]),),
    )
    init_memory_tables(db)
    row = db.execute(
        "SELECT source_type, tags FROM memories_v19 WHERE user_id='creator'"
    ).fetchone()
    assert row["source_type"] == "inferred"
    assert json.loads(row["tags"]) == ["legacy_source_unverified", "valide"]
    db.close()



def test_legacy_memory_migration_skips_non_text_identity_fields():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id, category, content, importance INTEGER,
            tags TEXT, access_count INTEGER, created_at TEXT, updated_at TEXT,
            UNIQUE(user_id, content)
        )
    """)
    db.executemany(
        "INSERT INTO memories VALUES (?, ?, ?, ?, 3, '[]', 0, 't0', 't1')",
        [
            (1, "creator", "general", "Souvenir valide"),
            (2, 42, "general", "Identité numérique"),
            (3, "creator", "general", b"contenu binaire"),
            (4, "creator", b"categorie binaire", "Catégorie mal formée"),
        ],
    )
    init_memory_tables(db)
    rows = db.execute(
        "SELECT user_id, category, content FROM memories_v19"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("creator", "general", "Souvenir valide")
    ]
    # Legacy source remains untouched; only the valid row is copied.
    assert db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 4
    db.close()



def test_episodic_search_does_not_expose_non_text_legacy_tags():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    db.execute(
        """INSERT INTO memories_v19
           (user_id, category, content, importance, source_type, confidence,
            tags, access_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 't0', 't1')""",
        ("creator", "general", "Souvenir valide", 3, "inferred", 0.5,
         json.dumps(["valide", 42, None, {"tag": "objet"}])),
    )
    results = search_episodic_memories(db, "creator")
    assert len(results) == 1
    assert results[0]["tags"] == ["valide"]
    db.close()



def test_legacy_memory_migration_skips_non_text_timestamps():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id, category, content, importance INTEGER,
            tags TEXT, access_count INTEGER, created_at, updated_at,
            UNIQUE(user_id, content)
        )
    """)
    db.executemany(
        "INSERT INTO memories VALUES (?, 'creator', 'general', ?, 3, '[]', 0, ?, 't1')",
        [
            (1, "Date valide", "2026-11-15T10:00:00+00:00"),
            (2, "Date binaire", b"2026-11-15"),
            (3, "Date numerique", 1763200800),
        ],
    )
    init_memory_tables(db)
    rows = db.execute(
        "SELECT content, created_at FROM memories_v19 ORDER BY id"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "Date valide"
    assert rows[0]["created_at"] == "2026-11-15T10:00:00+00:00"
    assert db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 3
    db.close()



def test_episodic_search_skips_corrupt_numeric_metadata():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute(
        """INSERT INTO memories_v19
           (id, user_id, category, content, importance, source_type, confidence,
            tags, access_count, created_at, updated_at)
           VALUES (1, 'creator', 'general', 'Souvenir endommage', 3,
                   'inferred', 'confiance invalide', '[]', 'acces invalide', 't0', 't1')"""
    )
    results = search_episodic_memories(db, "creator", "souvenir")
    assert results == []
    db.close()



def test_episodic_search_rejects_unknown_or_binary_provenance():
    from memory.episodic_memory import init_memory_tables, search_episodic_memories

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    # Simulate damaged legacy storage that bypassed the table CHECK constraint.
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute(
        """INSERT INTO memories_v19
           (user_id, category, content, importance, source_type, confidence,
            tags, access_count, created_at, updated_at)
           VALUES ('creator', 'general', 'Souvenir provenance inconnue', 3,
                   'fabricated', 0.5, '[]', 0, 't0', 't1')"""
    )
    db.execute(
        """INSERT INTO memories_v19
           (user_id, category, content, importance, source_type, confidence,
            tags, access_count, created_at, updated_at)
           VALUES ('creator', 'general', 'Souvenir provenance binaire', 3,
                   ?, 0.5, '[]', 0, 't0', 't1')""",
        (b"taught",),
    )
    assert search_episodic_memories(db, "creator") == []
    db.close()



def test_generic_memory_save_cannot_forge_confirmed_provenance():
    from memory.episodic_memory import init_memory_tables, save_episodic_memory

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    try:
        save_episodic_memory(
            db, "creator", "Fait non confirmé", source_type="confirmed"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("confirmed provenance must be rejected on insert")
    assert db.execute("SELECT COUNT(*) FROM memories_v19").fetchone()[0] == 0
    db.close()


def test_duplicate_memory_save_preserves_existing_provenance_and_confidence():
    from memory.episodic_memory import init_memory_tables, save_episodic_memory

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)
    save_episodic_memory(
        db, "creator", "Même fait", source_type="taught", confidence=0.91
    )
    save_episodic_memory(
        db, "creator", "Même fait", source_type="inferred", confidence=0.2
    )
    row = db.execute(
        "SELECT source_type, confidence FROM memories_v19 "
        "WHERE user_id='creator' AND content='Même fait'"
    ).fetchone()
    assert row["source_type"] == "taught"
    assert row["confidence"] == 0.91
    db.close()
