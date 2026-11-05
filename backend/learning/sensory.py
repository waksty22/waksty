"""Persisted sensory experiences shared by Chappie's learning systems.

Only observations and provenance are stored here; perception output is not
automatically promoted into personal vocabulary or factual knowledge.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_sensory_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sensory_observations (
            observation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            modality TEXT NOT NULL CHECK(modality IN ('audio', 'vision')),
            content TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5
                CHECK(confidence >= 0 AND confidence <= 1),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sensory_user_time
        ON sensory_observations(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS word_visual_associations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            word TEXT NOT NULL,
            observation_id TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, word, observation_id),
            FOREIGN KEY(observation_id)
                REFERENCES sensory_observations(observation_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_word_visual_user
        ON word_visual_associations(user_id, word);
    """)


def record_observation(
    db: sqlite3.Connection,
    user_id: str,
    modality: str,
    content: str,
    source: str,
    confidence: float = 0.5,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if modality not in {"audio", "vision"}:
        raise ValueError("Modalité sensorielle invalide.")
    content = str(content or "").strip()
    if not content or len(content) > 12000:
        raise ValueError("Observation vide ou trop longue.")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("La confiance doit être comprise entre 0 et 1.")
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False)
    observation_id = uuid.uuid4().hex
    created_at = utc_now()
    db.execute(
        """INSERT INTO sensory_observations
           (observation_id, user_id, modality, content, source,
            confidence, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (observation_id, user_id, modality, content, str(source)[:80],
         confidence, metadata_json, created_at),
    )
    return {
        "observation_id": observation_id,
        "user_id": user_id,
        "modality": modality,
        "content": content,
        "source": str(source)[:80],
        "confidence": confidence,
        "metadata": metadata or {},
        "created_at": created_at,
    }


def list_observations(
    db: sqlite3.Connection, user_id: str, limit: int = 30
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT observation_id, modality, content, source, confidence,
                  metadata_json, created_at
           FROM sensory_observations
           WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        result.append(item)
    return result


def associate_word_with_observation(
    db: sqlite3.Connection,
    user_id: str,
    word: str,
    observation_id: str,
    evidence: str = "Association visuelle validée par le créateur",
) -> dict[str, Any]:
    word = str(word or "").strip().casefold()
    if not word or len(word) > 80 or len(word.split()) != 1:
        raise ValueError("Indique un seul mot valide.")
    observation = db.execute(
        """SELECT observation_id FROM sensory_observations
           WHERE observation_id=? AND user_id=? AND modality='vision'""",
        (observation_id, user_id),
    ).fetchone()
    if observation is None:
        raise ValueError("Observation visuelle introuvable pour cet utilisateur.")
    vocabulary = db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
        (user_id, word),
    ).fetchone()
    if vocabulary is None:
        raise ValueError("Enseigne d'abord ce mot à Chappie.")
    now = utc_now()
    db.execute(
        """INSERT INTO word_visual_associations
           (user_id, word, observation_id, evidence, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, word, observation_id) DO UPDATE SET
             evidence=excluded.evidence""",
        (user_id, word, observation_id, str(evidence)[:500], now),
    )
    return {
        "word": word,
        "observation_id": observation_id,
        "vocabulary_state": vocabulary["state"],
        "association_saved": True,
    }
