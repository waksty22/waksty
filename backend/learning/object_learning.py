"""Progressive object learning for Chappie.

Properties are stored per user with explicit provenance. A visual description
never becomes a learned property unless a teaching/validation action records it.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

ALLOWED_PROPERTY_KEYS = {
    "couleur", "forme", "taille", "matiere", "texture",
    "poids", "temperature", "fonction", "usage", "etat",
    "son", "odeur", "gout", "autre",
}
MAX_VALUE_LENGTH = 500
MAX_EVIDENCE_LENGTH = 1000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_object_learning_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS object_properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            property_key TEXT NOT NULL,
            property_value TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK(source_type IN ('taught','observed','confirmed')),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, object_id, property_key, property_value),
            FOREIGN KEY(object_id) REFERENCES world_entities(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_object_properties_user_object
        ON object_properties(user_id, object_id);

        CREATE TABLE IF NOT EXISTS object_experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL CHECK(source_type IN ('taught','observed','confirmed')),
            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
            created_at TEXT NOT NULL,
            FOREIGN KEY(object_id) REFERENCES world_entities(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_object_experiences_user_object
        ON object_experiences(user_id, object_id, created_at DESC);
    """)


def _clean(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} doit être du texte.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f"{label} est vide ou trop long.")
    return value


def _require_known_object(
    db: sqlite3.Connection, user_id: str, word: str
) -> tuple[str, str]:
    word = _clean(word, "Mot", 80).casefold()
    vocab = db.execute(
        """SELECT state FROM personal_vocabulary
           WHERE user_id=? AND word=?""",
        (user_id, word),
    ).fetchone()
    if vocab is None or vocab["state"] not in (
        "recognized", "understood", "usable"
    ):
        raise ValueError(
            "Chappie doit d'abord avoir imité puis reconnu ce mot."
        )
    object_id = "object:" + word
    entity = db.execute(
        """SELECT id FROM world_entities
           WHERE id=? AND user_id=? AND entity_type='object'""",
        (object_id, user_id),
    ).fetchone()
    if entity is None:
        raise ValueError(
            "Montre d'abord cet objet à Chappie et valide son association visuelle."
        )
    return word, object_id


def teach_object_property(
    db: sqlite3.Connection,
    user_id: str,
    word: str,
    property_key: str,
    property_value: str,
    evidence: str = "",
    confidence: float = 0.9,
    source_type: str = "taught",
) -> dict[str, Any]:
    word, object_id = _require_known_object(db, user_id, word)
    key = _clean(property_key, "Propriété", 40).casefold()
    if key not in ALLOWED_PROPERTY_KEYS:
        raise ValueError("Type de propriété non autorisé.")
    value = _clean(property_value, "Valeur", MAX_VALUE_LENGTH)
    evidence = str(evidence or "").strip()[:MAX_EVIDENCE_LENGTH]
    if source_type not in {"taught", "observed", "confirmed"}:
        raise ValueError("Provenance invalide.")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Confiance invalide.") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("La confiance doit être comprise entre 0 et 1.")
    now = utc_now()
    db.execute(
        """INSERT INTO object_properties
           (user_id, object_id, property_key, property_value, source_type,
            confidence, evidence, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, object_id, property_key, property_value)
           DO UPDATE SET source_type=excluded.source_type,
             confidence=MAX(object_properties.confidence, excluded.confidence),
             evidence=excluded.evidence, updated_at=excluded.updated_at""",
        (user_id, object_id, key, value, source_type, confidence, evidence, now, now),
    )
    row = db.execute(
        """SELECT property_key, property_value, source_type, confidence,
                  evidence, created_at, updated_at
           FROM object_properties
           WHERE user_id=? AND object_id=? AND property_key=? AND property_value=?""",
        (user_id, object_id, key, value),
    ).fetchone()
    return {"word": word, **dict(row)}


def list_known_objects(db: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    objects = db.execute(
        """SELECT e.id, e.properties_json
           FROM world_entities e
           WHERE e.user_id=? AND e.entity_type='object'
           ORDER BY e.last_observed_at DESC""",
        (user_id,),
    ).fetchall()
    result = []
    for entity in objects:
        word = entity["id"].removeprefix("object:")
        vocab = db.execute(
            "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
            (user_id, word),
        ).fetchone()
        if vocab is None:
            continue
        properties = db.execute(
            """SELECT property_key, property_value, source_type, confidence, evidence
               FROM object_properties WHERE user_id=? AND object_id=?
               ORDER BY property_key, property_value""",
            (user_id, entity["id"]),
        ).fetchall()
        experiences = db.execute(
            """SELECT action, outcome, evidence, source_type, confidence, created_at
               FROM object_experiences WHERE user_id=? AND object_id=?
               ORDER BY created_at DESC LIMIT 20""",
            (user_id, entity["id"]),
        ).fetchall()
        result.append({
            "word": word,
            "vocabulary_state": vocab["state"],
            "properties": [dict(row) for row in properties],
            "experiences": [dict(row) for row in experiences],
        })
    return result


def compare_known_objects(
    db: sqlite3.Connection, user_id: str, first_word: str, second_word: str
) -> dict[str, Any]:
    first_word, first_id = _require_known_object(db, user_id, first_word)
    second_word, second_id = _require_known_object(db, user_id, second_word)
    if first_id == second_id:
        raise ValueError("Choisis deux objets différents.")
    def load(object_id: str) -> dict[str, set[str]]:
        rows = db.execute(
            """SELECT property_key, property_value FROM object_properties
               WHERE user_id=? AND object_id=?""",
            (user_id, object_id),
        ).fetchall()
        result: dict[str, set[str]] = {}
        for row in rows:
            result.setdefault(row["property_key"], set()).add(row["property_value"])
        return result
    first, second = load(first_id), load(second_id)
    shared = {}
    differences = {}
    for key in sorted(set(first) | set(second)):
        a, b = first.get(key, set()), second.get(key, set())
        common = sorted(a & b)
        only_a, only_b = sorted(a - b), sorted(b - a)
        if common:
            shared[key] = common
        if only_a or only_b:
            differences[key] = {
                first_word: only_a,
                second_word: only_b,
            }
    return {
        "first": first_word,
        "second": second_word,
        "shared_properties": shared,
        "differences": differences,
        "compared_property_count": len(set(first) | set(second)),
        "warning": "Une propriété absente signifie inconnue, pas opposée.",
    }


def record_object_experience(
    db: sqlite3.Connection,
    user_id: str,
    word: str,
    action: str,
    outcome: str,
    evidence: str = "",
    confidence: float = 0.6,
    source_type: str = "observed",
) -> dict[str, Any]:
    word, object_id = _require_known_object(db, user_id, word)
    action = _clean(action, "Action", 300)
    outcome = _clean(outcome, "Résultat", 1000)
    evidence = str(evidence or "").strip()[:MAX_EVIDENCE_LENGTH]
    if source_type not in {"taught", "observed", "confirmed"}:
        raise ValueError("Provenance invalide.")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ValueError("La confiance doit être comprise entre 0 et 1.")
    now = utc_now()
    cursor = db.execute(
        """INSERT INTO object_experiences
           (user_id, object_id, action, outcome, evidence, source_type,
            confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, object_id, action, outcome, evidence, source_type, confidence, now),
    )
    return {
        "id": cursor.lastrowid, "word": word, "action": action,
        "outcome": outcome, "evidence": evidence,
        "source_type": source_type, "confidence": confidence,
        "created_at": now,
        "promoted_to_property": False,
    }
