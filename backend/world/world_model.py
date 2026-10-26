"""Module de gestion du modèle du monde pour Chappie (entités, propriétés, relations)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_world_tables(db: sqlite3.Connection) -> None:
    """Initialise les tables du modèle du monde (entités et relations)."""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS world_entities (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        properties_json TEXT NOT NULL DEFAULT '{}',
        source_type TEXT NOT NULL CHECK(source_type IN ('observed', 'taught', 'inferred', 'confirmed')) DEFAULT 'observed',
        confidence REAL NOT NULL DEFAULT 0.8,
        last_observed_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS world_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_id TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK(source_type IN ('observed', 'taught', 'inferred', 'confirmed')) DEFAULT 'observed',
        confidence REAL NOT NULL DEFAULT 0.8,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(subject_id) REFERENCES world_entities(id) ON DELETE CASCADE,
        FOREIGN KEY(object_id) REFERENCES world_entities(id) ON DELETE CASCADE,
        UNIQUE(user_id, subject_id, predicate, object_id)
    );
    """)
    db.commit()


def upsert_world_entity(
    db: sqlite3.Connection,
    user_id: str,
    entity_id: str,
    entity_type: str,
    properties: dict[str, Any] | None = None,
    source_type: str = "observed",
    confidence: float = 0.8
) -> dict[str, Any]:
    """Crée ou met à jour une entité dans le modèle du monde."""
    entity_id = entity_id.strip()
    entity_type = entity_type.strip()
    if not entity_id or not entity_type:
        raise ValueError("L'identifiant et le type d'entité sont obligatoires.")
    
    confidence = max(0.0, min(1.0, float(confidence)))
    now = utc_now()
    props_json = json.dumps(properties or {}, ensure_ascii=False)

    db.execute("""
        INSERT INTO world_entities (id, user_id, entity_type, properties_json, source_type, confidence, last_observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            entity_type = excluded.entity_type,
            properties_json = excluded.properties_json,
            source_type = excluded.source_type,
            confidence = MAX(world_entities.confidence, excluded.confidence),
            last_observed_at = excluded.last_observed_at
    """, (entity_id, user_id, entity_type, props_json, source_type, confidence, now))
    db.commit()

    return {
        "id": entity_id,
        "type": entity_type,
        "properties": properties or {},
        "source_type": source_type,
        "confidence": confidence,
        "last_observed_at": now
    }


def get_world_entity(db: sqlite3.Connection, user_id: str, entity_id: str) -> dict[str, Any] | None:
    """Récupère une entité et ses propriétés."""
    row = db.execute("SELECT * FROM world_entities WHERE id = ? AND user_id = ?", (entity_id, user_id)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["properties"] = json.loads(item["properties_json"])
    except Exception:
        item["properties"] = {}
    del item["properties_json"]
    return item
