"""
Module de gestion de la mémoire épisodique et des sources de connaissances pour Chappie.

Fonctionnalités :
- Enregistrement des souvenirs avec traçabilité de leur source.
- Gestion de l'importance et du niveau de confiance.
- Recherche par contenu, catégorie et tags.
- Incrémentation sécurisée du compteur d'accès.
- Courbe de l'oubli progressive et maîtrisée.
- Isolation des données par utilisateur.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


log = logging.getLogger(__name__)

VALID_SOURCE_TYPES = {
    "observed",
    "taught",
    "inferred",
    "confirmed",
}

MAX_CONTENT_LENGTH = 4000
MAX_CATEGORY_LENGTH = 60
MAX_TAG_LENGTH = 40
MAX_TAGS = 20


def utc_now() -> str:
    """Retourne la date actuelle au format ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_source_type(source_type: str) -> str:
    """Valide la provenance d'un souvenir."""
    source = str(source_type or "taught").strip().lower()

    if source not in VALID_SOURCE_TYPES:
        raise ValueError(
            "source_type invalide. Valeurs autorisées : "
            + ", ".join(sorted(VALID_SOURCE_TYPES))
        )

    return source


def _normalize_content(content: str) -> str:
    """Nettoie et valide le contenu d'un souvenir."""
    if not isinstance(content, str):
        raise ValueError("Le contenu du souvenir doit être du texte.")

    content = content.strip()

    if not content:
        raise ValueError("Le contenu du souvenir ne peut pas être vide.")

    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(
            f"Le souvenir dépasse {MAX_CONTENT_LENGTH} caractères."
        )

    return content


def _normalize_tags(tags: list[str] | None) -> list[str]:
    """Nettoie les tags et limite leur nombre."""
    if tags is None:
        return []

    if not isinstance(tags, (list, tuple)):
        raise ValueError("Les tags doivent être fournis sous forme de liste.")

    safe_tags = []
    seen = set()

    for tag in tags:
        clean = str(tag).strip()[:MAX_TAG_LENGTH]

        if not clean:
            continue

        normalized = clean.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        safe_tags.append(clean)

        if len(safe_tags) >= MAX_TAGS:
            break

    return safe_tags


def init_memory_tables(db: sqlite3.Connection) -> None:
    """
    Initialise les tables de mémoire épisodique.

    Compatible avec une base SQLite existante :
    CREATE TABLE IF NOT EXISTS ne supprime pas les souvenirs déjà enregistrés.
    """
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories_v19 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER NOT NULL
                CHECK(importance BETWEEN 1 AND 5),
            source_type TEXT NOT NULL
                CHECK(
                    source_type IN (
                        'observed',
                        'taught',
                        'inferred',
                        'confirmed'
                    )
                )
                DEFAULT 'taught',
            confidence REAL NOT NULL DEFAULT 0.8
                CHECK(confidence BETWEEN 0.0 AND 1.0),
            tags TEXT NOT NULL DEFAULT '[]',
            access_count INTEGER NOT NULL DEFAULT 0
                CHECK(access_count >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        );

        CREATE INDEX IF NOT EXISTS idx_memories_v19_user
        ON memories_v19(user_id, importance DESC);

        CREATE INDEX IF NOT EXISTS idx_memories_v19_updated
        ON memories_v19(user_id, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_memories_v19_category
        ON memories_v19(user_id, category);
        """
    )

    db.commit()


def save_episodic_memory(
    db: sqlite3.Connection,
    user_id: str,
    content: str,
    category: str = "general",
    importance: int = 3,
    source_type: str = "taught",
    confidence: float = 0.8,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Enregistre ou actualise un souvenir épisodique.

    Si le souvenir existe déjà pour cet utilisateur :
    - son importance ne diminue pas ;
    - ses informations de provenance sont actualisées ;
    - sa date de mise à jour est actualisée ;
    - son compteur d'accès est conservé.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id est obligatoire.")

    user_id = user_id.strip()

    if len(user_id) > 80:
        raise ValueError("user_id dépasse 80 caractères.")

    content = _normalize_content(content)

    if not isinstance(category, str):
        raise ValueError("La catégorie doit être du texte.")

    category = category.strip()[:MAX_CATEGORY_LENGTH] or "general"

    source_type = _normalize_source_type(source_type)

    try:
        importance = int(importance)
        confidence = float(confidence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Importance ou confiance invalide.") from exc

    importance = max(1, min(5, importance))

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("La confiance doit être comprise entre 0 et 1.")

    safe_tags = _normalize_tags(tags)
    tags_json = json.dumps(safe_tags, ensure_ascii=False)
    now = utc_now()

    db.execute(
        """
        INSERT INTO memories_v19 (
            user_id,
            category,
            content,
            importance,
            source_type,
            confidence,
            tags,
            access_count,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)

        ON CONFLICT(user_id, content) DO UPDATE SET
            category = excluded.category,
            importance = MAX(
                memories_v19.importance,
                excluded.importance
            ),
            source_type = excluded.source_type,
            confidence = excluded.confidence,
            tags = excluded.tags,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            category,
            content,
            importance,
            source_type,
            confidence,
            tags_json,
            now,
            now,
        ),
    )

    db.commit()

    return {
        "saved": True,
        "content": content,
        "category": category,
        "importance": importance,
        "source_type": source_type,
        "confidence": confidence,
        "tags": safe_tags,
    }


def search_episodic_memories(
    db: sqlite3.Connection,
    user_id: str,
    query: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Recherche les souvenirs d'un utilisateur.

    La recherche examine :
    - le contenu ;
    - la catégorie ;
    - les tags.

    Chaque souvenir retourné voit son compteur d'accès augmenter.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id est obligatoire.")

    user_id = user_id.strip()

    if len(user_id) > 80:
        raise ValueError("user_id dépasse 80 caractères.")

    if query is None:
        query = ""

    if not isinstance(query, str):
        raise ValueError("La recherche doit être du texte.")

    query = query.strip()

    try:
        limit = int(limit)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("La limite de recherche doit être un nombre.") from exc

    limit = max(1, min(30, limit))

    if query:
        cursor = db.execute(
            """
            SELECT
                id,
                user_id,
                category,
                content,
                importance,
                source_type,
                confidence,
                tags,
                access_count,
                created_at,
                updated_at
            FROM memories_v19
            WHERE user_id = ?
              AND (
                    content LIKE ? COLLATE NOCASE
                    OR category LIKE ? COLLATE NOCASE
                    OR tags LIKE ? COLLATE NOCASE
              )
            ORDER BY
                importance DESC,
                access_count DESC,
                updated_at DESC
            LIMIT ?
            """,
            (
                user_id,
                f"%{query}%",
                f"%{query}%",
                f"%{query}%",
                limit,
            ),
        )
    else:
        cursor = db.execute(
            """
            SELECT
                id,
                user_id,
                category,
                content,
                importance,
                source_type,
                confidence,
                tags,
                access_count,
                created_at,
                updated_at
            FROM memories_v19
            WHERE user_id = ?
            ORDER BY
                importance DESC,
                access_count DESC,
                updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

    rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    memory_ids: list[int] = []

    for row in rows:
        item = dict(row)

        try:
            parsed_tags = json.loads(item.get("tags") or "[]")
            item["tags"] = (
                parsed_tags if isinstance(parsed_tags, list) else []
            )
        except (ValueError, TypeError):
            item["tags"] = []

        results.append(item)
        memory_ids.append(int(item["id"]))

    # Mise à jour atomique et limitée à l'utilisateur concerné.
    if memory_ids:
        db.executemany(
            """
            UPDATE memories_v19
            SET access_count = access_count + 1
            WHERE user_id = ? AND id = ?
            """,
            [(user_id, memory_id) for memory_id in memory_ids],
        )

        db.commit()

    return results


def apply_memory_decay(
    db: sqlite3.Connection,
    user_id: str,
    days: int = 30,
) -> int:
    """
    Applique une courbe de l'oubli contrôlée.

    Un souvenir perd un point d'importance lorsque :
    - il appartient à l'utilisateur ;
    - son importance est supérieure à 1 ;
    - il a été consulté moins de deux fois ;
    - il n'a pas été actualisé depuis le nombre de jours indiqué.

    Le seuil d'importance minimal reste fixé à 1.

    La date updated_at est actualisée après la décroissance :
    un souvenir ne perd donc pas un point à chaque passage de la boucle
    de maintenance.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id est obligatoire.")

    user_id = user_id.strip()

    if len(user_id) > 80:
        raise ValueError("user_id dépasse 80 caractères.")

    try:
        days = int(days)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Le nombre de jours est invalide.") from exc

    days = max(1, min(3650, days))

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()

    cursor = db.execute(
        """
        UPDATE memories_v19
        SET
            importance = importance - 1,
            updated_at = ?
        WHERE user_id = ?
          AND importance > 1
          AND access_count < 2
          AND (
                julianday(updated_at) < julianday(?)
                OR julianday(updated_at) IS NULL
          )
        """,
        (utc_now(), user_id, cutoff),
    )

    db.commit()

    return max(0, cursor.rowcount)


def get_memory_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    """Retourne des statistiques sur les souvenirs d'un utilisateur."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id est obligatoire.")

    user_id = user_id.strip()

    row = db.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(AVG(importance), 0) AS average_importance,
            COALESCE(AVG(confidence), 0) AS average_confidence,
            COALESCE(SUM(access_count), 0) AS total_accesses,
            SUM(CASE WHEN importance >= 4 THEN 1 ELSE 0 END)
                AS important_memories
        FROM memories_v19
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "average_importance": round(
            float(row["average_importance"] or 0), 2
        ),
        "average_confidence": round(
            float(row["average_confidence"] or 0), 3
        ),
        "total_accesses": int(row["total_accesses"] or 0),
        "important_memories": int(row["important_memories"] or 0),
    }



