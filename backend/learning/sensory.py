"""Persisted sensory experiences shared by Chappie's learning systems.

Only observations and provenance are stored here; perception output is not
automatically promoted into personal vocabulary or factual knowledge.
"""
from __future__ import annotations

import json
import math
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
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if not isinstance(modality, str) or modality not in {"audio", "vision"}:
        raise ValueError("Modalité sensorielle invalide.")
    if not isinstance(content, str):
        raise ValueError("Le contenu de l’observation doit être du texte.")
    content = content.strip()
    if not content or len(content) > 12000:
        raise ValueError("Observation vide ou trop longue.")
    if isinstance(confidence, bool):
        raise ValueError("Confiance invalide.")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Confiance sensorielle invalide.") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("La confiance doit être un nombre fini compris entre 0 et 1.")
    if not isinstance(source, str):
        raise ValueError("La source de l’observation doit être du texte.")
    source = source.strip()
    if not source or len(source) > 80:
        raise ValueError("La source doit contenir entre 1 et 80 caractères.")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("Les métadonnées doivent être un objet.")
    try:
        metadata_json = json.dumps(
            metadata, ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Les métadonnées doivent être sérialisables en JSON.") from exc
    observation_id = uuid.uuid4().hex
    created_at = utc_now()
    db.execute(
        """INSERT INTO sensory_observations
           (observation_id, user_id, modality, content, source,
            confidence, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (observation_id, user_id, modality, content, source,
         confidence, metadata_json, created_at),
    )
    return {
        "observation_id": observation_id,
        "user_id": user_id,
        "modality": modality,
        "content": content,
        "source": source,
        "confidence": confidence,
        "metadata": metadata,
        "created_at": created_at,
    }


def list_observations(
    db: sqlite3.Connection, user_id: str, limit: int = 30
) -> list[dict[str, Any]]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("La limite doit être un entier positif.")
    limit = min(limit, 100)
    rows = db.execute(
        """SELECT observation_id, modality, content, source, confidence,
                  metadata_json, created_at
           FROM sensory_observations
           WHERE user_id=? ORDER BY COALESCE(julianday(created_at), -1.0) DESC, observation_id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        raw_metadata = item.pop("metadata_json") or "{}"
        try:
            parsed_metadata = json.loads(raw_metadata)
        except (TypeError, ValueError):
            parsed_metadata = {}
        item["metadata"] = parsed_metadata if isinstance(parsed_metadata, dict) else {}
        result.append(item)
    return result


def associate_word_with_observation(
    db: sqlite3.Connection,
    user_id: str,
    word: str,
    observation_id: str,
    evidence: str,
) -> dict[str, Any]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if not isinstance(word, str):
        raise ValueError("Indique un seul mot valide.")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError("Identifiant d’observation invalide.")
    word = word.strip().casefold()
    if not word or len(word) > 80 or len(word.split()) != 1:
        raise ValueError("Indique un seul mot valide.")
    if not isinstance(evidence, str):
        raise ValueError("La preuve de validation visuelle doit être un texte explicite.")
    evidence = evidence.strip()
    if not evidence or len(evidence) > 500:
        raise ValueError("Décris la validation visuelle (1 à 500 caractères).")
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
    if vocabulary["state"] == "heard":
        raise ValueError(
            "Chappie doit d'abord avoir tenté d'imiter ce mot avant de l'associer à une image."
        )
    now = utc_now()
    if vocabulary["state"] == "imitated":
        db.execute(
            """UPDATE personal_vocabulary
               SET state='recognized',
                   updated_at=?
               WHERE user_id=? AND word=? AND state='imitated'""",
            (now, user_id, word),
        )
    db.execute(
        """INSERT INTO word_visual_associations
           (user_id, word, observation_id, evidence, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, word, observation_id) DO UPDATE SET
             evidence=excluded.evidence""",
        (user_id, word, observation_id, evidence, now),
    )
    return {
        "word": word,
        "observation_id": observation_id,
        "vocabulary_state": "recognized" if vocabulary["state"] == "imitated" else vocabulary["state"],
        "association_saved": True,
    }
