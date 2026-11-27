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
    sources = db.execute(
        """
        SELECT id, user_id, role, content, created_at
        FROM conversations
        WHERE user_id=?
        """,
        (user_id,),
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

    valid_source_ids = {
        row["id"]
        for row in db.execute(
            """
            SELECT id
            FROM conversations
            WHERE user_id=?
              AND typeof(id)='integer' AND id > 0
              AND role IN ('user', 'assistant')
              AND typeof(content)='text' AND length(trim(content)) > 0
              AND typeof(created_at)='text'
              AND julianday(created_at) IS NOT NULL
            """,
            (user_id,),
        ).fetchall()
    }

    # A source is indexed only when a provenance-valid event was found above.
    # A malformed or mismatched event must not hide an otherwise valid source.
    unindexed = len(valid_source_ids - indexed_source_ids)
    return {
        "source_table_available": True,
        "total_events": len(events),
        "valid_events": valid,
        "malformed_events": malformed,
        "missing_source_events": missing_source,
        "mismatched_source_events": mismatched_source,
        "unindexed_valid_sources": unindexed,
    }
