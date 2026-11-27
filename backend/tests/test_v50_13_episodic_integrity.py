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



def test_search_finds_old_relevant_memory_beyond_candidate_window():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Le café préféré du Créateur est torréfié léger",
            importance=1, source_type="taught", confidence=0.95,
        )
        db.execute(
            "UPDATE memories_v19 SET updated_at=?, created_at=? WHERE user_id=?",
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "owner"),
        )

        recent_rows = [
            (
                "owner", "general", f"Souvenir récent sans rapport {index}",
                5, "observed", 0.8, "[]", 0,
                f"2026-11-25T00:{index:06d}+00:00",
                f"2026-11-25T00:{index:06d}+00:00",
            )
            for index in range(2005)
        ]
        db.executemany(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            recent_rows,
        )
        db.commit()

        results = search_episodic_memories(db, "owner", "CAFE", limit=5)
        old_memory = next(
            item for item in results
            if item["content"] == "Le café préféré du Créateur est torréfié léger"
        )
        assert old_memory["source_type"] == "taught"
        assert old_memory["relevance_score"] > 0
        stored_access_count = db.execute(
            "SELECT access_count FROM memories_v19 WHERE user_id=? AND id=?",
            ("owner", old_memory["id"]),
        ).fetchone()[0]
        assert stored_access_count == 1
    finally:
        db.close()


def test_keyset_history_search_supports_tuple_rows_across_pages():
    # Default sqlite connections return tuples, not sqlite3.Row objects.
    db = sqlite3.connect(":memory:")
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Objet rare : un cadran mécanique ancien",
            importance=1, source_type="taught", confidence=0.9,
        )
        for index in range(505):
            save_episodic_memory(
                db, "owner", f"Note récente sans rapport {index}",
                importance=5, source_type="observed", confidence=0.7,
            )

        results = search_episodic_memories(db, "owner", "cadran mécanique", limit=5)
        assert any(
            item["content"] == "Objet rare : un cadran mécanique ancien"
            for item in results
        )
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


def test_episodic_search_orders_mixed_offsets_by_absolute_time():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(db, "owner", "Une montre est posée ici", importance=3)
        save_episodic_memory(db, "owner", "Une montre est rangée là", importance=3)
        db.execute("UPDATE memories_v19 SET updated_at=? WHERE content=?",
                   ("2026-11-26T09:00:00+02:00", "Une montre est posée ici"))
        db.execute("UPDATE memories_v19 SET updated_at=? WHERE content=?",
                   ("2026-11-26T08:30:00Z", "Une montre est rangée là"))
        recent = search_episodic_memories(db, "owner", "")
        assert [item["content"] for item in recent] == [
            "Une montre est rangée là", "Une montre est posée ici"]
        matching = search_episodic_memories(db, "owner", "montre")
        assert [item["content"] for item in matching] == [
            "Une montre est rangée là", "Une montre est posée ici"]
    finally:
        db.close()

def test_matching_memory_recall_keeps_oldest_best_match_with_bounded_top_k():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Le cadran ancien du Créateur est en laiton",
            importance=1, source_type="taught", confidence=0.95,
        )
        db.execute(
            "UPDATE memories_v19 SET updated_at=?, created_at=? WHERE content=?",
            ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00",
             "Le cadran ancien du Créateur est en laiton"),
        )
        db.executemany(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("owner", "general", f"Un cadran a été observé récemment {index}",
                 5, "observed", 0.8, "[]", 0,
                 f"2026-11-26T00:{index:06d}+00:00",
                 f"2026-11-26T00:{index:06d}+00:00")
                for index in range(2500)
            ],
        )
        db.commit()

        results = search_episodic_memories(
            db, "owner", "cadran ancien", limit=5
        )

        assert results
        assert results[0]["content"] == (
            "Le cadran ancien du Créateur est en laiton"
        )
        assert results[0]["relevance_score"] > results[1]["relevance_score"]
        assert len(results) <= 5
    finally:
        db.close()


def test_matching_memory_search_tolerates_malformed_ranking_metadata():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Souvenir valide du cadran", importance=3,
            source_type="taught", confidence=0.8,
        )
        db.execute("PRAGMA ignore_check_constraints = ON")
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "general", "Cadran ancien corrompu",
             sqlite3.Binary(b"bad"), "taught", 0.7, "[]", 0,
             "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        )
        db.commit()

        results = search_episodic_memories(
            db, "owner", "cadran", limit=5
        )

        assert any(item["content"] == "Souvenir valide du cadran" for item in results)
        assert all(item["content"] != "Cadran ancien corrompu" for item in results)
    finally:
        db.close()


def test_malformed_nonmatching_recent_fallback_is_excluded_before_ranking():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        init_memory_tables(db)
        save_episodic_memory(
            db, "owner", "Souvenir valide du cadran", importance=3,
            source_type="taught", confidence=0.8,
        )
        db.execute("PRAGMA ignore_check_constraints = ON")
        db.execute(
            """INSERT INTO memories_v19
               (user_id, category, content, importance, source_type, confidence,
                tags, access_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("owner", "general", "Ligne récente non pertinente",
             sqlite3.Binary(b"broken"), "taught", "not-a-number", "[]", 0,
             "2026-11-27T00:00:00+00:00", "2026-11-27T00:00:00+00:00"),
        )
        db.commit()

        results = search_episodic_memories(
            db, "owner", "souvenir cadran", limit=5
        )

        assert [item["content"] for item in results] == [
            "Souvenir valide du cadran"
        ]
    finally:
        db.close()
