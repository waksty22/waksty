import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.autobiographical import (
    find_related_autobiographical_events,
    init_autobiographical_tables,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    init_autobiographical_tables(db)
    return db


def add_event(db, event_id, user_id, content):
    db.execute(
        "INSERT INTO conversations VALUES (?, ?, 'user', ?, ?)",
        (event_id, user_id, content, f"2026-11-0{event_id}T10:00:00+00:00"),
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (id, user_id, source_conversation_id, actor, event_type,
             content, happened_at, importance, created_at)
        VALUES (?, ?, ?, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        (event_id, user_id, event_id, content,
         f"2026-11-0{event_id}T10:00:00+00:00",
         f"2026-11-0{event_id}T10:00:00+00:00"),
    )


def test_related_experiences_rank_shared_meaningful_terms_without_asserting_identity():
    db = make_db()
    add_event(db, 1, "creator", "J'ai appris à reconnaître une montre mécanique.")
    add_event(db, 2, "creator", "La montre mécanique possède un cadran rond.")
    add_event(db, 3, "creator", "Nous avons parlé du basket et du championnat.")

    results = find_related_autobiographical_events(db, "creator", 1)

    assert [item["id"] for item in results] == [2]
    assert set(results[0]["shared_terms"]) >= {"montre", "mecanique"}
    assert results[0]["relation_status"] == "candidate_only"
    assert "non confirmées" in results[0]["interpretation_warning"]
    db.close()


def test_related_experiences_require_two_meaningful_shared_terms():
    db = make_db()
    add_event(db, 1, "creator", "La montre est dans la boîte.")
    add_event(db, 2, "creator", "La montre est sur la table.")

    assert find_related_autobiographical_events(db, "creator", 1) == []
    db.close()


def test_related_experiences_are_read_only_and_user_scoped():
    db = make_db()
    add_event(db, 1, "alice", "Une montre mécanique avec cadran argenté.")
    add_event(db, 2, "alice", "La montre mécanique a un cadran noir.")
    add_event(db, 3, "bob", "La montre mécanique a un cadran bleu.")

    before = db.execute(
        "SELECT COUNT(*) FROM autobiographical_links"
    ).fetchone()[0]
    results = find_related_autobiographical_events(db, "alice", 1)
    after = db.execute(
        "SELECT COUNT(*) FROM autobiographical_links"
    ).fetchone()[0]

    assert [item["id"] for item in results] == [2]
    assert before == after == 0
    assert find_related_autobiographical_events(db, "alice", 999) == []
    db.close()
