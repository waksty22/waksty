"""Read-only integrity report must expose blocked sources without repair."""
from __future__ import annotations

import sqlite3

from memory.autobiographical import init_autobiographical_tables
from memory.autobiographical_integrity import autobiographical_integrity_report


def test_integrity_report_distinguishes_missing_mismatched_and_unindexed_sources():
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
    timestamp = "2026-11-27T10:00:00Z"
    db.executemany(
        "INSERT INTO conversations VALUES (?, 'creator', ?, ?, ?)",
        [
            (1, "user", "Source cohérente", timestamp),
            (2, "user", "Source modifiée", timestamp),
            (3, "assistant", "Source valide non indexée", timestamp),
            (4, "user", "Horodatage invalide", "pas-une-date"),
        ],
    )
    db.executemany(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', ?, 'user', 'user_statement', ?, ?, 3, ?)
        """,
        [
            (1, "Source cohérente", timestamp, timestamp),
            (2, "Ancien contenu copié", timestamp, timestamp),
            (999, "Souvenir orphelin", timestamp, timestamp),
        ],
    )
    db.execute(
        """
        INSERT INTO autobiographical_events
            (user_id, source_conversation_id, actor, event_type, content,
             happened_at, importance, created_at)
        VALUES ('creator', 3, 'assistant', '', 'Source valide non indexée',
                ?, 3, ?)
        """,
        (timestamp, timestamp),
    )
    db.commit()

    before = db.execute(
        "SELECT id, source_conversation_id, content FROM autobiographical_events ORDER BY id"
    ).fetchall()
    report = autobiographical_integrity_report(db, "creator")
    after = db.execute(
        "SELECT id, source_conversation_id, content FROM autobiographical_events ORDER BY id"
    ).fetchall()

    assert report == {
        "source_table_available": True,
        "total_events": 4,
        "valid_events": 1,
        "malformed_events": 1,
        "missing_source_events": 1,
        "mismatched_source_events": 1,
        "unindexed_valid_sources": 2,
    }
    assert [tuple(row) for row in before] == [tuple(row) for row in after]
    db.close()


def test_integrity_report_handles_missing_source_table_without_writes():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_autobiographical_tables(db)

    report = autobiographical_integrity_report(db, "creator")

    assert report == {
        "source_table_available": False,
        "total_events": 0,
        "valid_events": 0,
        "malformed_events": 0,
        "missing_source_events": 0,
        "mismatched_source_events": 0,
        "unindexed_valid_sources": 0,
    }
    db.close()
