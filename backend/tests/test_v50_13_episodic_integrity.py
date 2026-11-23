"""Corruption-resistant decay and statistics for episodic memories."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from memory.episodic_memory import (
    apply_memory_decay,
    get_memory_statistics,
    init_memory_tables,
    save_episodic_memory,
    search_episodic_memories,
)


def test_decay_and_statistics_ignore_malformed_persisted_rows():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Souvenir valide", importance=3,
            source_type="taught", confidence=0.8,
        )
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        db.execute(
            "UPDATE memories_v19 SET updated_at=? WHERE user_id=?",
            (old, "owner"),
        )

        # Bypass table CHECK constraints to simulate legacy/database corruption.
        db.execute("PRAGMA ignore_check_constraints = ON")
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "test", "Importance binaire", sqlite3.Binary(b"bad"),
             "taught", 0.7, "[]", 0, old, old),
        )
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "test", "Confiance binaire", 4, "taught",
             sqlite3.Binary(b"bad"), "[]", 0, old, old),
        )
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "test", "Provenance inconnue", 4, "invented",
             0.9, "[]", 0, old, old),
        )
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "test", "Accès binaire", 4, "taught",
             0.9, "[]", sqlite3.Binary(b"bad"), old, old),
        )
        db.commit()

        stats = get_memory_statistics(db, "owner")
        assert stats == {
            "total": 1,
            "average_importance": 3.0,
            "average_confidence": 0.8,
            "total_accesses": 0,
            "important_memories": 0,
        }

        changed = apply_memory_decay(db, "owner", days=30)
        assert changed == 1
        valid = db.execute(
            "SELECT importance FROM memories_v19 WHERE content=?",
            ("Souvenir valide",),
        ).fetchone()
        assert valid["importance"] == 2

        malformed = db.execute(
            "SELECT importance FROM memories_v19 WHERE content=?",
            ("Importance binaire",),
        ).fetchone()
        assert malformed["importance"] == b"bad"
    finally:
        db.close()


def test_decay_does_not_treat_malformed_timestamp_as_old():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(db, "owner", "Date invalide", importance=3)
        db.execute(
            "UPDATE memories_v19 SET updated_at=? WHERE content=?",
            (sqlite3.Binary(b"not-a-date"), "Date invalide"),
        )
        db.commit()
        assert apply_memory_decay(db, "owner", days=30) == 0
        row = db.execute(
            "SELECT importance FROM memories_v19 WHERE content=?",
            ("Date invalide",),
        ).fetchone()
        assert row["importance"] == 3
    finally:
        db.close()



def test_search_does_not_overflow_maximum_sqlite_access_counter():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(db, "owner", "Souvenir compteur maximal")
        db.execute(
            "UPDATE memories_v19 SET access_count=? WHERE content=?",
            (9223372036854775807, "Souvenir compteur maximal"),
        )
        db.commit()

        results = search_episodic_memories(
            db, "owner", "compteur maximal", limit=5
        )
        assert len(results) == 1
        assert results[0]["access_count"] == 9223372036854775807
        stored = db.execute(
            "SELECT access_count FROM memories_v19 WHERE content=?",
            ("Souvenir compteur maximal",),
        ).fetchone()
        assert stored["access_count"] == 9223372036854775807
    finally:
        db.close()
