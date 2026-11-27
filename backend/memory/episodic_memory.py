
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
import re
import sqlite3
import unicodedata
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


def _timestamp_sort_key(value: Any) -> float:
    """Normalize ISO timestamps to absolute UTC instants for stable ranking."""
    if not isinstance(value, str) or not value.strip():
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        return float("-inf")


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
    """Valide la provenance d'un souvenir, y compris l'état confirmé."""
    if source_type is None:
        return "taught"
    if not isinstance(source_type, str):
        raise ValueError("La provenance doit être du texte.")
    source = source_type.strip().lower()

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

    if not isinstance(tags, list):
        raise ValueError("Les tags doivent être fournis sous forme de liste.")

    if any(not isinstance(tag, str) for tag in tags):
        raise ValueError("Chaque tag doit être du texte.")

    safe_tags: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        clean = tag.strip()[:MAX_TAG_LENGTH]

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
    if isinstance(importance, bool) or not isinstance(importance, int):
        raise ValueError("L'importance doit être un entier.")
    return max(1, min(5, importance))


def _normalize_confidence(confidence: float) -> float:
    """Valide la confiance entre 0 et 1."""
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
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
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("La limite doit être un entier.")
    return max(minimum, min(maximum, limit))


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


def _is_valid_search_candidate(item: dict[str, Any]) -> bool:
    """Reject malformed persisted rows before either search ranking path."""
    if not isinstance(item.get("id"), int) or isinstance(item.get("id"), bool):
        return False
    if item["id"] < 1:
        return False
    if not isinstance(item.get("content"), str) or not item["content"].strip():
        return False
    if not isinstance(item.get("category"), str) or not item["category"].strip():
        return False
    if item.get("source_type") not in VALID_SOURCE_TYPES:
        return False
    importance = item.get("importance")
    if isinstance(importance, bool) or not isinstance(importance, int):
        return False
    if not 1 <= importance <= 5:
        return False
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
        return False
    access_count = item.get("access_count")
    return (
        isinstance(access_count, int)
        and not isinstance(access_count, bool)
        and access_count >= 0
    )


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
            # Legacy rows are untrusted: never turn malformed values into
            # plausible user memories through str() coercion.
            raw_user_id = row["user_id"]
            raw_content = row["content"]
            raw_category = row["category"]
            if not isinstance(raw_user_id, str):
                continue
            if not isinstance(raw_content, str):
                continue
            if raw_category is not None and not isinstance(raw_category, str):
                continue
            user_id = _normalize_user_id(raw_user_id)
            content = _normalize_content(raw_content)
            category = _normalize_category(raw_category or "general")
            importance = _normalize_importance(row["importance"])
            access_count = _normalize_limit(row["access_count"], 0, 2_000_000_000)
        except (ValueError, TypeError):
            continue
        try:
            tags = json.loads(row.get("tags") or "[]")
        except (ValueError, TypeError):
            tags = []
        legacy_tags = (
            [tag for tag in tags if isinstance(tag, str)]
            if isinstance(tags, list) else []
        )
        safe_tags = _normalize_tags(
            ["legacy_source_unverified"] + legacy_tags
        )
        raw_created_at = row.get("created_at")
        raw_updated_at = row.get("updated_at")
        # Do not turn BLOBs, numbers, or other malformed legacy timestamps
        # into plausible-looking strings during migration.
        if raw_created_at is not None and not isinstance(raw_created_at, str):
            continue
        if raw_updated_at is not None and not isinstance(raw_updated_at, str):
            continue
        now = utc_now()
        created_at = raw_created_at.strip() if raw_created_at and raw_created_at.strip() else now
        updated_at = raw_updated_at.strip() if raw_updated_at and raw_updated_at.strip() else created_at
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
    allow_confirmation: bool = False,
) -> dict[str, Any]:
    """
    Enregistre ou actualise un souvenir épisodique.

    Si le souvenir existe déjà pour cet utilisateur :
    - son importance ne diminue pas ;
    - sa provenance et sa confiance restent inchangées par défaut ;
    - elles ne peuvent être remplacées que par un appel interne autorisé ;
    - sa date de mise à jour est actualisée ;
    - son compteur d'accès est conservé.
    """
    user_id = _normalize_user_id(user_id)
    content = _normalize_content(content)
    category = _normalize_category(category)
    importance = _normalize_importance(importance)
    source_type = _normalize_source_type(source_type)
    if source_type == "confirmed" and allow_confirmation is not True:
        raise ValueError(
            "La provenance 'confirmed' exige un appel interne explicitement "
            "autorisé ; les enregistrements ordinaires ne peuvent pas la définir."
        )
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

            -- A generic save may refresh a memory, but it cannot rewrite
            -- its original provenance or confidence. In particular, a
            -- later model inference must not downgrade a user-confirmed fact.
            source_type = CASE
                WHEN ? = 1 THEN excluded.source_type
                ELSE memories_v19.source_type
            END,
            confidence = CASE
                WHEN ? = 1 THEN excluded.confidence
                ELSE memories_v19.confidence
            END,
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
            1 if allow_confirmation is True else 0,
            1 if allow_confirmation is True else 0,
        ),
    )

    persisted = db.execute(
        """SELECT importance, source_type, confidence
           FROM memories_v19 WHERE user_id=? AND content=?""",
        (user_id, content),
    ).fetchone()
    if persisted is None:
        raise RuntimeError("Le souvenir enregistré est introuvable.")

    return {
        "saved": True,
        "content": content,
        "category": category,
        "importance": persisted[0],
        "source_type": persisted[1],
        "confidence": persisted[2],
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

    terms = _memory_search_terms(query) if query else []
    columns = """
        SELECT id, user_id, category, content, importance, source_type,
               confidence, tags, access_count, created_at, updated_at
        FROM memories_v19
        WHERE user_id = ?
    """
    if not terms:
        cursor = db.execute(
            columns + " ORDER BY importance DESC, access_count DESC, COALESCE(julianday(updated_at), -1.0) DESC, id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cursor.fetchall()
    else:
        # Keep a recent candidate pool for fallback, but scan the user's
        # complete history in small pages for query matches. Python performs
        # Unicode accent folding; a deeply nested SQL REPLACE expression is
        # not portable to libSQL and can overflow its parser.
        recent_cursor = db.execute(
            columns + " ORDER BY importance DESC, COALESCE(julianday(updated_at), -1.0) DESC, id DESC LIMIT 2000",
            (user_id,),
        )
        recent_rows = [
            item
            for item in (
                _row_to_dict(row, recent_cursor)
                for row in recent_cursor.fetchall()
            )
            if _is_valid_search_candidate(item)
        ]

        # Only the best `limit` matching memories can appear in the
        # final answer. Keep that top-k while paging instead of accumulating
        # every historical match in RAM.
        matching_rows: list[dict[str, Any]] = []

        def matching_rank(item: dict[str, Any]) -> tuple[float, int, float, int, float]:
            try:
                importance = int(item.get("importance") or 0)
            except (TypeError, ValueError, OverflowError):
                importance = 0
            try:
                confidence = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError, OverflowError):
                confidence = 0.0
            try:
                access_count = int(item.get("access_count") or 0)
            except (TypeError, ValueError, OverflowError):
                access_count = 0
            if not math.isfinite(confidence):
                confidence = 0.0
            return (
                float(item.get("relevance_score") or 0.0),
                importance,
                confidence,
                access_count,
                _timestamp_sort_key(item.get("updated_at")),
            )

        last_seen_id: int | None = None
        page_size = 500
        while True:
            if last_seen_id is None:
                page_cursor = db.execute(
                    columns + " ORDER BY id DESC LIMIT ?",
                    (user_id, page_size),
                )
            else:
                page_cursor = db.execute(
                    columns + " AND id < ? ORDER BY id DESC LIMIT ?",
                    (user_id, last_seen_id, page_size),
                )
            page = page_cursor.fetchall()
            if not page:
                break
            for raw_row in page:
                item = _row_to_dict(raw_row, page_cursor)
                if not _is_valid_search_candidate(item):
                    continue
                content = item["content"]
                category = item["category"]
                try:
                    parsed_tags = json.loads(item.get("tags") or "[]")
                    tags = (
                        [tag for tag in parsed_tags if isinstance(tag, str)]
                        if isinstance(parsed_tags, list) else []
                    )
                except (ValueError, TypeError):
                    tags = []
                searchable = " ".join(
                    [content, category, " ".join(tags)]
                ).casefold()
                folded = unicodedata.normalize("NFKD", searchable)
                folded = "".join(
                    char for char in folded if not unicodedata.combining(char)
                )
                tokens = set(re.findall(r"[a-z0-9]{2,}", folded))
                matched_terms = set(terms) & tokens
                if matched_terms:
                    item["relevance_score"] = round(
                        len(matched_terms) / max(1, len(terms)) * 10,
                        3,
                    )
                    # A full phrase match receives the same bonus used by
                    # the final ranking pass.
                    normalized_phrase = unicodedata.normalize(
                        "NFKD", query.casefold()
                    )
                    normalized_phrase = "".join(
                        char for char in normalized_phrase
                        if not unicodedata.combining(char)
                    )
                    phrase_tokens = re.findall(r"[a-z0-9]{2,}", normalized_phrase)
                    token_list = re.findall(r"[a-z0-9]{2,}", folded)
                    phrase_match = bool(
                        phrase_tokens
                        and any(
                            token_list[index:index + len(phrase_tokens)] == phrase_tokens
                            for index in range(len(token_list) - len(phrase_tokens) + 1)
                        )
                    )
                    if phrase_match:
                        item["relevance_score"] = round(
                            item["relevance_score"] + 3, 3
                        )
                    matching_rows.append(item)
                    matching_rows.sort(key=matching_rank, reverse=True)
                    del matching_rows[limit:]
                    continue
                # Preserve the existing exact-phrase fallback for queries
                # whose terms were filtered as stop words.
                normalized_phrase = unicodedata.normalize(
                    "NFKD", query.casefold()
                )
                normalized_phrase = "".join(
                    char for char in normalized_phrase
                    if not unicodedata.combining(char)
                )
                phrase_tokens = re.findall(r"[a-z0-9]{2,}", normalized_phrase)
                token_list = re.findall(r"[a-z0-9]{2,}", folded)
                if phrase_tokens and any(
                    token_list[index:index + len(phrase_tokens)] == phrase_tokens
                    for index in range(len(token_list) - len(phrase_tokens) + 1)
                ):
                    matching_rows.append(item)
            # Keyset pagination avoids increasingly expensive OFFSET scans
            # and remains stable if newer memories are inserted mid-search.
            last_seen_id = int(_row_to_dict(page[-1], page_cursor)["id"])

        # Historical matches take priority, then recent memories are retained
        # as fallback. IDs ensure a record is never ranked twice.
        merged_rows: dict[int, dict[str, Any]] = {}
        for item in matching_rows:
            row_id = item.get("id")
            if isinstance(row_id, int) and not isinstance(row_id, bool):
                merged_rows[row_id] = item
        for item in recent_rows:
            row_id = item.get("id")
            if isinstance(row_id, int) and not isinstance(row_id, bool):
                merged_rows.setdefault(row_id, item)
        rows = list(merged_rows.values())
        cursor = recent_cursor

    results: list[dict[str, Any]] = []
    normalized_query = query.casefold()
    for row in rows:
        item = _row_to_dict(row, cursor)
        # Defensive read boundary: damaged rows must not crash ranking or
        # leak coerced values into the shared cognitive context.
        if not isinstance(item.get("id"), int) or isinstance(item.get("id"), bool):
            continue
        if not isinstance(item.get("content"), str) or not isinstance(item.get("category"), str):
            continue
        source_type = item.get("source_type")
        if not isinstance(source_type, str) or source_type not in VALID_SOURCE_TYPES:
            continue
        if not isinstance(item.get("importance"), int) or isinstance(item.get("importance"), bool):
            continue
        raw_confidence = item.get("confidence")
        if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
            continue
        try:
            confidence_value = float(raw_confidence)
        except (OverflowError, TypeError, ValueError):
            continue
        if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
            continue
        if not isinstance(item.get("access_count"), int) or isinstance(item.get("access_count"), bool):
            continue
        try:
            parsed_tags = json.loads(item.get("tags") or "[]")
            item["tags"] = (
                [tag for tag in parsed_tags if isinstance(tag, str)]
                if isinstance(parsed_tags, list) else []
            )
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
        searchable_tokens = re.findall(r"[a-z0-9]{2,}", searchable_folded)
        searchable_token_set = set(searchable_tokens)
        matched = sum(1 for term in terms if term in searchable_token_set)

        normalized_query_folded = unicodedata.normalize("NFKD", normalized_query)
        normalized_query_folded = "".join(
            char for char in normalized_query_folded
            if not unicodedata.combining(char)
        )
        query_tokens = re.findall(r"[a-z0-9]{2,}", normalized_query_folded)
        phrase_match = bool(
            query_tokens
            and any(
                searchable_tokens[index:index + len(query_tokens)] == query_tokens
                for index in range(len(searchable_tokens) - len(query_tokens) + 1)
            )
        )
        if query and matched == 0 and not phrase_match:
            continue
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
                _timestamp_sort_key(item.get("updated_at")),
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
              AND typeof(access_count) = 'integer'
              AND access_count >= 0
              AND access_count < 9223372036854775807
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
          AND typeof(importance) = 'integer'
          AND importance BETWEEN 2 AND 5
          AND typeof(access_count) = 'integer'
          AND access_count BETWEEN 0 AND 1
          AND typeof(content) = 'text' AND length(trim(content)) > 0
          AND typeof(category) = 'text'
          AND typeof(source_type) = 'text'
          AND source_type IN ('observed', 'taught', 'inferred')
          AND typeof(confidence) IN ('integer', 'real')
          AND confidence BETWEEN 0.0 AND 1.0
          AND typeof(updated_at) = 'text'
          AND julianday(updated_at) IS NOT NULL
          AND julianday(updated_at) < julianday(?)
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
          AND typeof(id) = 'integer'
          AND typeof(user_id) = 'text'
          AND typeof(content) = 'text' AND length(trim(content)) > 0
          AND typeof(category) = 'text'
          AND typeof(importance) = 'integer'
          AND importance BETWEEN 1 AND 5
          AND typeof(source_type) = 'text'
          AND source_type IN ('observed', 'taught', 'inferred', 'confirmed')
          AND typeof(confidence) IN ('integer', 'real')
          AND confidence BETWEEN 0.0 AND 1.0
          AND typeof(access_count) = 'integer' AND access_count >= 0
          AND typeof(created_at) = 'text'
          AND typeof(updated_at) = 'text'
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
