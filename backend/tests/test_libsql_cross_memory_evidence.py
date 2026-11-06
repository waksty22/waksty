"""V36.9 — conservative cross-reference between two real memory stores.

All fixtures use a local in-memory libSQL database; no remote Turso access.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.libsql_adapter import adapt_libsql_connection


@pytest.fixture
def cross_memory_db():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    from memory.autobiographical import init_autobiographical_tables
    from memory.episodic_memory import init_memory_tables

    db.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    init_autobiographical_tables(db)
    init_memory_tables(db)
    db.execute(
        """INSERT INTO conversations (user_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        ("creator", "user", "Je préfère apprendre avec des exemples concrets.", "2026-11-07T10:00:00Z"),
    )
    db.execute(
        """INSERT INTO autobiographical_events
           (user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("creator", 1, "user", "user_statement",
         "Je préfère apprendre avec des exemples concrets.",
         "2026-11-07T10:00:00Z", 3, "2026-11-07T10:00:00Z"),
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()


def test_exact_text_overlap_is_linked_but_never_promoted_to_truth(cross_memory_db):
    from cognition.shared_brain import get_shared_brain_snapshot
    from memory.episodic_memory import save_episodic_memory

    save_episodic_memory(
        cross_memory_db,
        "creator",
        "  JE PRÉFÈRE apprendre avec des exemples concrets. ",
        source_type="taught",
        confidence=0.95,
    )
    snapshot = get_shared_brain_snapshot(cross_memory_db, "creator")

    assert len(snapshot["cross_memory_evidence"]) == 1
    link = snapshot["cross_memory_evidence"][0]
    assert link["match_type"] == "exact_normalized_text"
    assert link["evidence_status"] == "textual_overlap_only"
    assert link["verified_fact"] is False
    assert link["independent_corroboration"] is False
    assert link["autobiographical_event_id"] == 1
    assert link["episodic_memory_id"] == 1
    assert snapshot["rules"]["textual_match_is_not_truth"] is True
    assert snapshot["rules"]["repeated_storage_is_not_independent_corroboration"] is True


def test_similar_but_not_identical_text_is_not_semantically_matched(cross_memory_db):
    from cognition.shared_brain import get_shared_brain_snapshot
    from memory.episodic_memory import save_episodic_memory

    save_episodic_memory(
        cross_memory_db,
        "creator",
        "J'apprends mieux quand on me montre des exemples.",
        source_type="inferred",
        confidence=0.6,
    )
    snapshot = get_shared_brain_snapshot(cross_memory_db, "creator")

    assert snapshot["cross_memory_evidence"] == []
    assert snapshot["statistics"]["cross_memory_evidence_links"] == 0


def test_cross_memory_evidence_is_isolated_per_user(cross_memory_db):
    from cognition.shared_brain import get_shared_brain_snapshot
    from memory.episodic_memory import save_episodic_memory

    save_episodic_memory(
        cross_memory_db,
        "other-user",
        "Je préfère apprendre avec des exemples concrets.",
        source_type="confirmed",
        confidence=1.0,
    )
    snapshot = get_shared_brain_snapshot(cross_memory_db, "creator")
    other = get_shared_brain_snapshot(cross_memory_db, "other-user")

    assert snapshot["cross_memory_evidence"] == []
    assert other["cross_memory_evidence"] == []


def test_missing_memory_tables_produce_no_cross_memory_links():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    try:
        from cognition.shared_brain import get_shared_brain_snapshot

        snapshot = get_shared_brain_snapshot(db, "creator")
        assert snapshot["cross_memory_evidence"] == []
        assert snapshot["statistics"]["cross_memory_evidence_links"] == 0
    finally:
        db.close()
