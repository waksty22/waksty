"""Read-only integrity diagnostics for autobiographical memory.

This module deliberately never repairs, deletes, or rewrites memory rows.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .autobiographical import (
    _is_valid_autobiographical_event,
    _validated_user_id,
)


def autobiographical_integrity_report(
    db: sqlite3.Connection, user_id: str
) -> dict[str, int | bool]:
    """Describe memory/source inconsistencies without mutating either table."""
    user_id = _validated_user_id(user_id)
    source_table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversations'"
    ).fetchone()
    if source_table is None:
        return {
            "source_table_available": False,
            "total_events": int(db.execute(
                "SELECT COUNT(*) FROM autobiographical_events WHERE user_id=?",
                (user_id,),
            ).fetchone()[0]),
            "valid_events": 0,
            "malformed_events": 0,
            "missing_source_events": 0,
            "mismatched_source_events": 0,
            "unindexed_valid_sources": 0,
        }

    events = db.execute(
        """
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE user_id=?
        ORDER BY id
        """,
        (user_id,),
    ).fetchall()
    # Only materialize source rows referenced by autobiographical events.
    # The full conversation table may be much larger than the memory index.
    sources = db.execute(
        """
        SELECT id, user_id, role, content, created_at
        FROM conversations
        WHERE user_id=?
          AND id IN (
              SELECT source_conversation_id
              FROM autobiographical_events
              WHERE user_id=?
          )
        """,
        (user_id, user_id),
    ).fetchall()
    source_by_id = {row["id"]: row for row in sources}

    malformed = 0
    missing_source = 0
    mismatched_source = 0
    valid = 0
    indexed_source_ids: set[int] = set()
    for row in events:
        item = dict(row)
        if not _is_valid_autobiographical_event(item):
            malformed += 1
            continue
        source = source_by_id.get(item["source_conversation_id"])
        if source is None:
            missing_source += 1
            continue
        content = source["content"]
        matches = (
            source["role"] == item["actor"]
            and isinstance(content, str)
            and content.strip()[:8000] == item["content"]
            and source["created_at"] == item["happened_at"]
        )
        if not matches:
            mismatched_source += 1
            continue
        valid += 1
        indexed_source_ids.add(item["source_conversation_id"])

    valid_source_count = int(db.execute(
        """
        SELECT COUNT(*)
        FROM conversations
        WHERE user_id=?
          AND typeof(id)='integer' AND id > 0
          AND role IN ('user', 'assistant')
          AND typeof(content)='text' AND length(trim(content, char(9)||char(10)||char(11)||char(12)||char(13)||' '||char(28)||char(29)||char(30)||char(31)||char(133)||char(160)||char(5760)||char(8192)||char(8193)||char(8194)||char(8195)||char(8196)||char(8197)||char(8198)||char(8199)||char(8200)||char(8201)||char(8202)||char(8232)||char(8233)||char(8239)||char(8287)||char(12288))) > 0
          AND typeof(created_at)='text'
          AND julianday(created_at) IS NOT NULL
        """,
        (user_id,),
    ).fetchone()[0])

    # Count indexed sources in bounded batches rather than retaining every
    # valid conversation ID in Python. The batches stay below SQLite's
    # traditional 999-variable limit.
    indexed_valid_source_count = 0
    indexed_ids = sorted(indexed_source_ids)
    for offset in range(0, len(indexed_ids), 500):
        batch = indexed_ids[offset:offset + 500]
        placeholders = ",".join("?" for _ in batch)
        indexed_valid_source_count += int(db.execute(
            f"""
            SELECT COUNT(*)
            FROM conversations
            WHERE user_id=?
              AND id IN ({placeholders})
              AND typeof(id)='integer' AND id > 0
              AND role IN ('user', 'assistant')
              AND typeof(content)='text' AND length(trim(content, char(9)||char(10)||char(11)||char(12)||char(13)||' '||char(28)||char(29)||char(30)||char(31)||char(133)||char(160)||char(5760)||char(8192)||char(8193)||char(8194)||char(8195)||char(8196)||char(8197)||char(8198)||char(8199)||char(8200)||char(8201)||char(8202)||char(8232)||char(8233)||char(8239)||char(8287)||char(12288))) > 0
              AND typeof(created_at)='text'
              AND julianday(created_at) IS NOT NULL
            """,
            (user_id, *batch),
        ).fetchone()[0])

    # A malformed or mismatched event must not hide an otherwise valid source.
    unindexed = valid_source_count - indexed_valid_source_count
    return {
        "source_table_available": True,
        "total_events": len(events),
        "valid_events": valid,
        "malformed_events": malformed,
        "missing_source_events": missing_source,
        "mismatched_source_events": mismatched_source,
        "unindexed_valid_sources": unindexed,
    }
