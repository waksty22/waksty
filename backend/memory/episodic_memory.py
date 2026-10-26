"""Module de gestion de la mémoire épisodique et des sources de connaissances pour Chappie."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_memory_tables(db: sqlite3.Connection) -> None:
    """Initialise les tables de mémoire enrichies avec traçabilité des sources."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS memories_v19 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
        source_type TEXT NOT NULL CHECK(source_type IN ('observed', 'taught', 'inferred', 'confirmed')) DEFAULT 'taught',
        confidence REAL NOT NULL DEFAULT 0.8,
        tags TEXT NOT NULL DEFAULT '[]',
        access_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, content)
    );
    
    CREATE INDEX IF NOT EXISTS idx_memories_v19_user ON memories_v19(user_id, importance DESC);
    """)
    db.commit()


def save_episodic_memory(
    db: sqlite3.Connection,
    user_id: str,
    content: str,
    category: str = "general",
    importance: int = 3,
    source_type: str = "taught",
    confidence: float = 0.8,
    tags: list[str] | None = None
) -> dict[str, Any]:
    """Enregistre un souvenir épisodique avec sa source et son niveau de confiance."""
    content = content.strip()
    if not content:
        raise ValueError("Le contenu du souvenir ne peut pas être vide.")
    
    importance = max(1, min(5, int(importance)))
    confidence = max(0.0, min(1.0, float(confidence)))
    safe_tags = [str(t).strip()[:40] for t in (tags or []) if str(t).strip()][:20]
    tags_json = json.dumps(safe_tags, ensure_ascii=False)
    now = utc_now()

    db.execute("""
        INSERT INTO memories_v19 (user_id, category, content, importance, source_type, confidence, tags, access_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(user_id, content) DO UPDATE SET
            category = excluded.category,
            importance = MAX(memories_v19.importance, excluded.importance),
            source_type = excluded.source_type,
            confidence = excluded.confidence,
            tags = excluded.tags,
            updated_at = excluded.updated_at
    """, (user_id, category.strip()[:60], content, importance, source_type, confidence, tags_json, now, now))
    db.commit()

    return {
        "saved": True,
        "content": content,
        "category": category,
        "importance": importance,
        "source_type": source_type,
        "confidence": confidence,
        "tags": safe_tags
    }


def search_episodic_memories(db: sqlite3.Connection, user_id: str, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """Recherche des souvenirs dans la mémoire épisodique."""
    limit = max(1, min(30, int(limit)))
    if query.strip():
        cursor = db.execute("""
            SELECT id, category, content, importance, source_type, confidence, tags, access_count, created_at
            FROM memories_v19
            WHERE user_id = ? AND (content LIKE ? OR category LIKE ?)
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
        """, (user_id, f"%{query}%", f"%{query}%", limit))
    else:
        cursor = db.execute("""
            SELECT id, category, content, importance, source_type, confidence, tags, access_count, created_at
            FROM memories_v19
            WHERE user_id = ?
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
        """, (user_id, limit))

    results = []
    for row in cursor.fetchall():
        item = dict(row)
        try:
            item["tags"] = json.loads(item["tags"])
        except Exception:
            item["tags"] = []
        results.append(item)
    return results
