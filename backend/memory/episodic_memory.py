
"""
Module de gestion de la mémoire épisodique et des sources de connaissances
pour Chappie V19.3.

Fonctionnalités :
- Enregistrement des souvenirs avec traçabilité de leur source.
- Gestion de l'importance et du niveau de confiance.
- Recherche par contenu, catégorie et tags.
- Incrémentation sécurisée du compteur d'accès.
- Courbe de l'oubli progressive et maîtrisée.
- Isolation des données par utilisateur.
- Compatibilité avec les connexions SQLite existantes.
"""

from __future__ import annotations

import json
import logging
import math
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

MAX_USER_ID_LENGTH = 80
MAX_CONTENT_LENGTH = 4000
MAX_CATEGORY_LENGTH = 60
MAX_TAG_LENGTH = 40
MAX_TAGS = 20
MAX_SEARCH_LENGTH = 200


def utc_now() -> str:
    """Retourne la date actuelle au format ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_user_id(user_id: str) -> str:
    """Valide et normalise l'identifiant utilisateur."""
    if not isinstance(user_id, str):
        raise ValueError("user_id doit être du texte.")

    user_id = user_id.strip()

    if not user_id:
        raise ValueError("user_id est obligatoire.")

    if len(user_id) > MAX_USER_ID_LENGTH:
        raise ValueError(
            f"user_id dépasse {MAX_USER_ID_LENGTH} caractères."
        )

    return user_id


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


def _normalize_category(category: str) -> str:
    """Nettoie et valide la catégorie."""
    if not isinstance(category, str):
        raise ValueError("La catégorie doit être du texte.")

    category = category.strip()[:MAX_CATEGORY_LENGTH]

    return category or "general"


def _normalize_tags(tags: list[str] | None) -> list[str]:
    """Nettoie les tags et limite leur nombre."""
    if tags is None:
        return []

    if not isinstance(tags, (list, tuple)):
        raise ValueError("Les tags doivent être fournis sous forme de liste.")

    safe_tags: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        if tag is None:
            continue

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


def _normalize_importance(importance: int) -> int:
    """Valide et borne l'importance entre 1 et 5."""
    if isinstance(importance, bool):
        raise ValueError("L'importance doit être un nombre entier.")

    try:
        value = int(importance)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Importance invalide.") from exc

    return max(1, min(5, value))


def _normalize_confidence(confidence: float) -> float:
    """Valide la confiance entre 0 et 1."""
    if isinstance(confidence, bool):
        raise ValueError("La confiance doit être un nombre.")

    try:
        value = float(confidence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Confiance invalide.") from exc

    if not math.isfinite(value):
        raise ValueError("La confiance doit être une valeur finie.")

    if not 0.0 <= value <= 1.0:
        raise ValueError(
            "La confiance doit être comprise entre 0 et 1."
        )

    return value


def _normalize_limit(limit: int, minimum: int, maximum: int) -> int:
    """Valide une limite numérique."""
    if isinstance(limit, bool):
        raise ValueError("La limite doit être un nombre entier.")

    try:
        value = int(limit)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("La limite doit être un nombre.") from exc

    return max(minimum, min(maximum, value))


def _escape_like(value: str) -> str:
    """
    Échappe les caractères spéciaux SQL LIKE.

    Empêche notamment qu'un caractère '%' ou '_' fourni
    par l'utilisateur soit interprété comme un joker.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _row_to_dict(row: Any, cursor: sqlite3.Cursor) -> dict[str, Any]:
    """Convertit un résultat SQLite en dictionnaire."""
    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return dict(row)

    if hasattr(row, "keys"):
        return dict(row)

    columns = [
        description[0]
        for description in (cursor.description or [])
    ]

    return dict(zip(columns, row))


def init_memory_tables(db: sqlite3.Connection) -> None:
    """
    Initialise les tables de mémoire épisodique.

    Compatible avec une base SQLite existante :
    CREATE TABLE IF NOT EXISTS ne supprime pas les souvenirs existants.
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

        CREATE INDEX IF NOT EXISTS idx_memories_v19_access
        ON memories_v19(user_id, access_count DESC);
        """
    )
    migrate_legacy_memories(db)


def migrate_legacy_memories(db: sqlite3.Connection) -> int:
    """Copy legacy memories without deleting or falsely upgrading their provenance."""
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()
    if not exists:
        return 0
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(memories)").fetchall()
    }
    required = {"user_id", "category", "content", "importance", "tags",
                "access_count", "created_at", "updated_at"}
    if not required.issubset(columns):
        log.warning("Migration mémoire ignorée : schéma legacy incomplet.")
        return 0
    cursor = db.execute(
        """SELECT user_id,category,content,importance,tags,access_count,
                  created_at,updated_at FROM memories"""
    )
    migrated = 0
    for raw in cursor.fetchall():
        row = _row_to_dict(raw, cursor)
        try:
            user_id = _normalize_user_id(str(row["user_id"] or ""))
            content = _normalize_content(str(row["content"] or ""))
            category = _normalize_category(str(row["category"] or "general"))
            importance = _normalize_importance(row["importance"])
            access_count = _normalize_limit(row["access_count"], 0, 2_000_000_000)
        except (ValueError, TypeError):
            continue
        try:
            tags = json.loads(row.get("tags") or "[]")
        except (ValueError, TypeError):
            tags = []
        safe_tags = _normalize_tags(
            ["legacy_source_unverified"] + (tags if isinstance(tags, list) else [])
        )
        now = utc_now()
        created_at = str(row.get("created_at") or now)
        updated_at = str(row.get("updated_at") or created_at)
        result = db.execute(
            """INSERT OR IGNORE INTO memories_v19
               (user_id,category,content,importance,source_type,confidence,tags,
                access_count,created_at,updated_at)
               VALUES (?,?,?,?, 'inferred',0.5,?,?,?,?)""",
            (user_id, category, content, importance,
             json.dumps(safe_tags, ensure_ascii=False), access_count,
             created_at, updated_at),
        )
        migrated += max(0, result.rowcount)
    return migrated


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
    user_id = _normalize_user_id(user_id)
    content = _normalize_content(content)
    category = _normalize_category(category)
    importance = _normalize_importance(importance)
    source_type = _normalize_source_type(source_type)
    confidence = _normalize_confidence(confidence)

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

    return {
        "saved": True,
        "content": content,
        "category": category,
        "importance": importance,
        "source_type": source_type,
        "confidence": confidence,
        "tags": safe_tags,
    }


def _memory_search_terms(query: str) -> list[str]:
    """Return distinct, accent-insensitive terms useful for French memory search."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", query.casefold())
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    stop_words = {
        "a", "au", "aux", "avec", "ce", "ces", "dans", "de", "des",
        "du", "elle", "en", "et", "eux", "il", "je", "la", "le",
        "les", "leur", "lui", "ma", "mais", "me", "mes", "moi",
        "mon", "ne", "nos", "notre", "nous", "on", "ou", "par",
        "pas", "pour", "que", "qui", "sa", "se", "ses", "son",
        "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une",
        "vos", "votre", "vous", "the", "and", "for", "with",
    }
    terms: list[str] = []
    for term in re.findall(r"[a-z0-9]{2,}", normalized):
        if term not in stop_words and term not in terms:
            terms.append(term)
    return terms[:12]


def search_episodic_memories(
    db: sqlite3.Connection,
    user_id: str,
    query: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Retrieve relevant episodic memories using multi-term lexical matching.

    Exact phrases receive a relevance bonus, but a query need not appear
    verbatim: matching content, category, or tags across several words is
    enough. Results remain isolated by user and preserve source/confidence.
    """
    user_id = _normalize_user_id(user_id)

    if query is None:
        query = ""
    if not isinstance(query, str):
        raise ValueError("La recherche doit être du texte.")

    query = query.strip()[:MAX_SEARCH_LENGTH]
    limit = _normalize_limit(limit, 1, 30)

    columns = """
        SELECT id, user_id, category, content, importance, source_type,
               confidence, tags, access_count, created_at, updated_at
        FROM memories_v19
        WHERE user_id = ?
    """
    if not query:
        cursor = db.execute(
            columns + " ORDER BY importance DESC, access_count DESC, updated_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cursor.fetchall()
    else:
        terms = _memory_search_terms(query)
        if not terms:
            terms = [query.casefold()]
        predicates = []
        params: list[Any] = [user_id]
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            predicates.append(
                "(content LIKE ? ESCAPE '\\\\' COLLATE NOCASE "
                "OR category LIKE ? ESCAPE '\\\\' COLLATE NOCASE "
                "OR tags LIKE ? ESCAPE '\\\\' COLLATE NOCASE)"
            )
            params.extend((pattern, pattern, pattern))
        cursor = db.execute(
            columns + " AND (" + " OR ".join(predicates) + ") LIMIT 250",
            tuple(params),
        )
        rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    normalized_query = query.casefold()
    terms = _memory_search_terms(query) if query else []
    for row in rows:
        item = _row_to_dict(row, cursor)
        try:
            parsed_tags = json.loads(item.get("tags") or "[]")
            item["tags"] = parsed_tags if isinstance(parsed_tags, list) else []
        except (ValueError, TypeError):
            item["tags"] = []

        searchable = " ".join([
            str(item.get("content") or ""),
            str(item.get("category") or ""),
            " ".join(str(tag) for tag in item["tags"]),
        ]).casefold()
        searchable_folded = unicodedata.normalize("NFKD", searchable)
        searchable_folded = "".join(
            char for char in searchable_folded
            if not unicodedata.combining(char)
        )
        matched = sum(
            1 for term in terms if term in searchable_folded
        )
        phrase_match = bool(normalized_query and normalized_query in searchable)
        # Relevance is lexical evidence, not a claim that the memory is true.
        item["relevance_score"] = round(
            (matched / max(1, len(terms))) * 10
            + (3 if phrase_match else 0),
            3,
        )
        results.append(item)

    if query:
        results.sort(
            key=lambda item: (
                item["relevance_score"],
                int(item.get("importance") or 0),
                float(item.get("confidence") or 0),
                int(item.get("access_count") or 0),
                str(item.get("updated_at") or ""),
            ),
            reverse=True,
        )
    results = results[:limit]

    if results:
        db.executemany(
            """
            UPDATE memories_v19
            SET access_count = access_count + 1
            WHERE user_id = ? AND id = ?
            """,
            [(user_id, int(item["id"])) for item in results],
        )

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

    La date updated_at est actualisée après la décroissance.
    Un souvenir ne perd donc pas un point à chaque passage
    de la boucle de maintenance.
    """
    user_id = _normalize_user_id(user_id)
    days = _normalize_limit(days, 1, 3650)

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()

    now = utc_now()

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
        (now, user_id, cutoff),
    )

    return max(0, cursor.rowcount)


def get_memory_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, Any]:
    """Retourne des statistiques sur les souvenirs d'un utilisateur."""
    user_id = _normalize_user_id(user_id)

    cursor = db.execute(
        """
        SELECT
            COUNT(*) AS total,

            COALESCE(
                AVG(importance),
                0
            ) AS average_importance,

            COALESCE(
                AVG(confidence),
                0
            ) AS average_confidence,

            COALESCE(
                SUM(access_count),
                0
            ) AS total_accesses,

            COALESCE(
                SUM(
                    CASE
                        WHEN importance >= 4 THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS important_memories

        FROM memories_v19
        WHERE user_id = ?
        """,
        (user_id,),
    )

    row = _row_to_dict(cursor.fetchone(), cursor)

    return {
        "total": int(row["total"] or 0),

        "average_importance": round(
            float(row["average_importance"] or 0),
            2,
        ),

        "average_confidence": round(
            float(row["average_confidence"] or 0),
            3,
        ),

        "total_accesses": int(
            row["total_accesses"] or 0
        ),

        "important_memories": int(
            row["important_memories"] or 0
        ),
    }
