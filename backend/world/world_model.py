"""
Chappie V19.3 — modèle du monde.

Gestion :
- Des entités (personnes, objets, lieux, animaux, concepts, projets...)
- Des propriétés associées aux entités
- Des relations entre les entités
- De la provenance des informations
- Du niveau de confiance accordé aux informations
- De l'évolution des observations dans le temps

Sources autorisées :
- observed  : information observée par Chappie
- taught    : information enseignée à Chappie
- inferred  : information déduite par Chappie
- confirmed : information confirmée

Ce module conserve les noms et signatures des fonctions existantes
afin de préserver la compatibilité avec les autres modules.
"""

from __future__ import annotations

import json
import math
import sqlite3

from datetime import datetime, timezone
from typing import Any


# ============================================================
# CONFIGURATION
# ============================================================

VALID_SOURCE_TYPES = {
    "observed",
    "taught",
    "inferred",
    "confirmed",
}

DEFAULT_CONFIDENCE = 0.8

MAX_ID_LENGTH = 200
MAX_TYPE_LENGTH = 100
MAX_PREDICATE_LENGTH = 200
MAX_QUERY_LENGTH = 500


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def utc_now() -> str:
    """Retourne la date actuelle au format ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _validate_text(
    value: str,
    field_name: str,
    max_length: int = MAX_ID_LENGTH
) -> str:
    """Nettoie et valide une chaîne de caractères."""

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} doit être une chaîne de caractères."
        )

    value = value.strip()

    if not value:
        raise ValueError(
            f"{field_name} est obligatoire."
        )

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} ne peut pas dépasser "
            f"{max_length} caractères."
        )

    return value


def _validate_user_id(user_id: str) -> str:
    """Valide l'identifiant de l'utilisateur."""

    return _validate_text(
        user_id,
        "user_id",
        MAX_ID_LENGTH
    )


def _validate_source_type(source_type: str) -> str:
    """Vérifie la provenance d'une information."""

    if not isinstance(source_type, str):
        raise ValueError(
            "source_type doit être une chaîne."
        )

    source_type = source_type.strip().lower()

    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            "source_type invalide. Valeurs autorisées : "
            + ", ".join(sorted(VALID_SOURCE_TYPES))
        )

    return source_type


def _validate_confidence(confidence: float) -> float:
    """Garantit un niveau de confiance compris entre 0 et 1."""

    if isinstance(confidence, bool):
        raise ValueError(
            "confidence doit être un nombre."
        )

    try:
        confidence = float(confidence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "confidence doit être un nombre."
        ) from exc

    if not math.isfinite(confidence):
        raise ValueError(
            "confidence doit être un nombre fini."
        )

    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            "confidence doit être comprise entre 0 et 1."
        )

    return confidence


def _validate_properties(
    properties: dict[str, Any] | None
) -> dict[str, Any]:
    """Valide les propriétés et leur compatibilité JSON."""

    if properties is None:
        return {}

    if not isinstance(properties, dict):
        raise ValueError(
            "Les propriétés doivent être un dictionnaire."
        )

    try:
        json.dumps(
            properties,
            ensure_ascii=False,
            allow_nan=False
        )

    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Les propriétés contiennent une valeur "
            f"non compatible JSON : {exc}"
        ) from exc

    return properties


def _escape_like(value: str) -> str:
    """Échappe les caractères spéciaux SQL LIKE."""

    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _row_to_dict(
    row: Any,
    columns: list[str] | None = None
) -> dict[str, Any] | None:
    """
    Convertit un résultat SQLite en dictionnaire.

    Compatible avec :
    - sqlite3.Row ;
    - dictionnaires ;
    - tuples avec noms de colonnes fournis.
    """

    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return dict(row)

    if hasattr(row, "keys"):
        return dict(row)

    if columns is not None:
        return dict(zip(columns, row))

    raise TypeError(
        "Impossible de convertir le résultat SQLite "
        "sans connaître les noms des colonnes."
    )


def _fetch_dict(
    db: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = ()
) -> dict[str, Any] | None:
    """Exécute une requête et convertit le résultat."""

    cursor = db.execute(query, params)
    row = cursor.fetchone()

    if row is None:
        return None

    columns = [
        column[0]
        for column in (cursor.description or [])
    ]

    return _row_to_dict(row, columns)


def _fetch_dicts(
    db: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """Exécute une requête et convertit tous les résultats."""

    cursor = db.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        return []

    columns = [
        column[0]
        for column in (cursor.description or [])
    ]

    return [
        _row_to_dict(row, columns)
        for row in rows
    ]


def _normalize_limit(
    limit: int,
    minimum: int = 1,
    maximum: int = 100
) -> int:
    """Valide et borne une limite de résultats."""

    if isinstance(limit, bool):
        raise ValueError(
            "limit doit être un nombre entier."
        )

    try:
        value = int(limit)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "limit doit être un nombre entier."
        ) from exc

    return max(minimum, min(maximum, value))


# ============================================================
# INITIALISATION DES TABLES
# ============================================================

def init_world_tables(db: sqlite3.Connection) -> None:
    """
    Initialise les tables du modèle du monde.

    Les tables existantes sont conservées.
    Les index supplémentaires accélèrent les recherches.
    """

    # Active les clés étrangères pour cette connexion SQLite.
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS world_entities (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            properties_json TEXT NOT NULL DEFAULT '{}',

            source_type TEXT NOT NULL
                CHECK(source_type IN (
                    'observed',
                    'taught',
                    'inferred',
                    'confirmed'
                ))
                DEFAULT 'observed',

            confidence REAL NOT NULL DEFAULT 0.8
                CHECK(confidence >= 0 AND confidence <= 1),

            last_observed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS world_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT NOT NULL,

            subject_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_id TEXT NOT NULL,

            source_type TEXT NOT NULL
                CHECK(source_type IN (
                    'observed',
                    'taught',
                    'inferred',
                    'confirmed'
                ))
                DEFAULT 'observed',

            confidence REAL NOT NULL DEFAULT 0.8
                CHECK(confidence >= 0 AND confidence <= 1),

            updated_at TEXT NOT NULL,

            FOREIGN KEY(subject_id)
                REFERENCES world_entities(id)
                ON DELETE CASCADE,

            FOREIGN KEY(object_id)
                REFERENCES world_entities(id)
                ON DELETE CASCADE,

            UNIQUE(
                user_id,
                subject_id,
                predicate,
                object_id
            )
        );

        CREATE INDEX IF NOT EXISTS idx_world_entities_user
            ON world_entities(user_id);

        CREATE INDEX IF NOT EXISTS idx_world_entities_type
            ON world_entities(user_id, entity_type);

        CREATE INDEX IF NOT EXISTS idx_world_entities_observed
            ON world_entities(user_id, last_observed_at);

        CREATE INDEX IF NOT EXISTS idx_world_relations_user
            ON world_relations(user_id);

        CREATE INDEX IF NOT EXISTS idx_world_relations_subject
            ON world_relations(user_id, subject_id);

        CREATE INDEX IF NOT EXISTS idx_world_relations_object
            ON world_relations(user_id, object_id);

        CREATE INDEX IF NOT EXISTS idx_world_relations_predicate
            ON world_relations(user_id, predicate);
        """
    )


# ============================================================
# CRÉATION / MISE À JOUR DES ENTITÉS
# ============================================================

def upsert_world_entity(
    db: sqlite3.Connection,
    user_id: str,
    entity_id: str,
    entity_type: str = "general",
    properties: dict[str, Any] | None = None,
    source_type: str = "observed",
    confidence: float = 0.8
) -> dict[str, Any]:
    """
    Crée une entité ou met à jour une entité existante.

    Une information moins fiable ne remplace pas les propriétés
    déjà enregistrées avec un niveau de confiance supérieur.

    Un utilisateur ne peut pas modifier l'entité d'un autre utilisateur.
    """

    user_id = _validate_user_id(user_id)

    entity_id = _validate_text(
        entity_id,
        "entity_id",
        MAX_ID_LENGTH
    )

    entity_type = _validate_text(
        entity_type,
        "entity_type",
        MAX_TYPE_LENGTH
    ).casefold()

    source_type = _validate_source_type(source_type)
    confidence = _validate_confidence(confidence)
    properties = _validate_properties(properties)

    props_json = json.dumps(
        properties,
        ensure_ascii=False,
        allow_nan=False
    )

    now = utc_now()

    # Vérification préalable de la propriété de l'entité.
    existing = _fetch_dict(
        db,
        """
        SELECT user_id, confidence
        FROM world_entities
        WHERE id = ?
        """,
        (entity_id,)
    )

    if existing and existing["user_id"] != user_id:
        raise PermissionError(
            "Cette entité appartient à un autre utilisateur."
        )

    db.execute(
        """
        INSERT INTO world_entities (
            id,
            user_id,
            entity_type,
            properties_json,
            source_type,
            confidence,
            last_observed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(id) DO UPDATE SET

            entity_type = CASE
                WHEN excluded.confidence >= world_entities.confidence
                THEN excluded.entity_type
                ELSE world_entities.entity_type
            END,

            properties_json = CASE
                WHEN excluded.confidence >= world_entities.confidence
                THEN excluded.properties_json
                ELSE world_entities.properties_json
            END,

            source_type = CASE
                WHEN excluded.confidence >= world_entities.confidence
                THEN excluded.source_type
                ELSE world_entities.source_type
            END,

            confidence = MAX(
                world_entities.confidence,
                excluded.confidence
            ),

            last_observed_at = excluded.last_observed_at

        WHERE world_entities.user_id = excluded.user_id
        """,
        (
            entity_id,
            user_id,
            entity_type,
            props_json,
            source_type,
            confidence,
            now
        )
    )

    result = get_world_entity(
        db,
        user_id,
        entity_id
    )

    if result is None:
        raise RuntimeError(
            "L'entité n'a pas pu être enregistrée."
        )

    return result


# ============================================================
# RÉCUPÉRATION D'UNE ENTITÉ
# ============================================================

def get_world_entity(
    db: sqlite3.Connection,
    user_id: str,
    entity_id: str
) -> dict[str, Any] | None:
    """
    Récupère une entité appartenant à un utilisateur.

    Les propriétés JSON sont automatiquement converties
    en dictionnaire Python.
    """

    user_id = _validate_user_id(user_id)

    entity_id = _validate_text(
        entity_id,
        "entity_id",
        MAX_ID_LENGTH
    )

    item = _fetch_dict(
        db,
        """
        SELECT *
        FROM world_entities
        WHERE id = ? AND user_id = ?
        """,
        (entity_id, user_id)
    )

    if item is None:
        return None

    try:
        properties = json.loads(
            item.get("properties_json") or "{}"
        )

        if not isinstance(properties, dict):
            properties = {}

    except (json.JSONDecodeError, TypeError, ValueError):
        properties = {}

    item["properties"] = properties
    item.pop("properties_json", None)

    return item


# ============================================================
# CRÉATION / MISE À JOUR DES RELATIONS
# ============================================================

def add_world_relation(
    db: sqlite3.Connection,
    user_id: str,
    subject_id: str,
    object_id: str,
    relation_type: str = "relates_to",
    weight: float = 1.0,
    source_type: str = "observed",
    confidence: float = 0.8
) -> dict[str, Any]:
    """
    Crée ou met à jour une relation orientée :

        Sujet -> Prédicat (relation_type) -> Objet

    Supporte à la fois les signatures (db, user_id, subject, target, relation_type, weight)
    et (db, user_id, subject_id, predicate, object_id, source_type, confidence).
    """

    # Gestion de la compatibilité des noms de paramètres selon les appels
    predicate = relation_type
    
    user_id = _validate_user_id(user_id)

    subject_id = _validate_text(
        subject_id,
        "subject_id",
        MAX_ID_LENGTH
    )

    predicate = _validate_text(
        predicate,
        "predicate",
        MAX_PREDICATE_LENGTH
    ).casefold()

    object_id = _validate_text(
        object_id,
        "object_id",
        MAX_ID_LENGTH
    )

    source_type = _validate_source_type(source_type)
    confidence = _validate_confidence(confidence)

    now = utc_now()

    # Vérification du sujet.
    subject = _fetch_dict(
        db,
        """
        SELECT id
        FROM world_entities
        WHERE id = ? AND user_id = ?
        """,
        (subject_id, user_id)
    )

    if subject is None:
        raise ValueError(
            f"Le sujet '{subject_id}' n'existe pas "
            "dans le modèle du monde de cet utilisateur."
        )

    # Vérification de l'objet.
    obj = _fetch_dict(
        db,
        """
        SELECT id
        FROM world_entities
        WHERE id = ? AND user_id = ?
        """,
        (object_id, user_id)
    )

    if obj is None:
        raise ValueError(
            f"L'objet '{object_id}' n'existe pas "
            "dans le modèle du monde de cet utilisateur."
        )

    db.execute(
        """
        INSERT INTO world_relations (
            user_id,
            subject_id,
            predicate,
            object_id,
            source_type,
            confidence,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(
            user_id,
            subject_id,
            predicate,
            object_id
        )
        DO UPDATE SET

            source_type = CASE
                WHEN excluded.confidence >= world_relations.confidence
                THEN excluded.source_type
                ELSE world_relations.source_type
            END,

            confidence = MAX(
                world_relations.confidence,
                excluded.confidence
            ),

            updated_at = excluded.updated_at
        """,
        (
            user_id,
            subject_id,
            predicate,
            object_id,
            source_type,
            confidence,
            now
        )
    )

    result = _fetch_dict(
        db,
        """
        SELECT
            id,
            user_id,
            subject_id,
            predicate,
            object_id,
            source_type,
            confidence,
            updated_at
        FROM world_relations
        WHERE user_id = ?
          AND subject_id = ?
          AND predicate = ?
          AND object_id = ?
        """,
        (
            user_id,
            subject_id,
            predicate,
            object_id
        )
    )

    if result is None:
        raise RuntimeError(
            "La relation n'a pas pu être enregistrée."
        )

    return result


# ============================================================
# RÉCUPÉRATION DES RELATIONS D'UNE ENTITÉ
# ============================================================

def get_entity_relations(
    db_or_user_id: sqlite3.Connection | str,
    user_id_or_entity_id: str,
    entity_id_opt: str | None = None
) -> list[dict[str, Any]]:
    """
    Récupère toutes les relations dans lesquelles une entité apparaît.
    
    Compatible avec les deux signatures possibles :
    1. get_entity_relations(db, user_id, entity_id)
    2. get_entity_relations(user_id, entity_id) [rétrocompatibilité]
    """
    # Accept native SQLite and the explicit libsql adapter without
    # mistaking ordinary user-id strings for connection objects.
    if isinstance(db_or_user_id, sqlite3.Connection) or callable(
        getattr(db_or_user_id, "execute", None)
    ):
        db = db_or_user_id
        user_id = _validate_user_id(user_id_or_entity_id)
        entity_id = _validate_text(entity_id_opt, "entity_id", MAX_ID_LENGTH)
        close_db = False
    else:
        # Signature alternative sans connexion SQLite explicite
        from server import db_connection
        db = db_connection()
        close_db = True
        user_id = _validate_user_id(db_or_user_id)
        entity_id = _validate_text(user_id_or_entity_id, "entity_id", MAX_ID_LENGTH)

    try:
        return _fetch_dicts(
            db,
            """
            SELECT
                id,
                user_id,
                subject_id,
                predicate,
                object_id,
                source_type,
                confidence,
                updated_at

            FROM world_relations

            WHERE user_id = ?
              AND (
                  subject_id = ?
                  OR object_id = ?
              )

            ORDER BY updated_at DESC, id DESC
            """,
            (
                user_id,
                entity_id,
                entity_id
            )
        )
    finally:
        if close_db:
            db.close()


# ============================================================
# RÉSUMÉ ET STATISTIQUES DU MONDE
# ============================================================

def get_world_summary(user_id: str) -> dict[str, Any]:
    """
    Renvoie un résumé complet des entités et relations du monde pour un utilisateur.
    """
    user_id = _validate_user_id(user_id)
    from server import db_connection
    with db_connection() as db:
        entities = db.execute(
            "SELECT * FROM world_entities WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        relations = db.execute(
            "SELECT * FROM world_relations WHERE user_id = ?",
            (user_id,)
        ).fetchall()

        return {
            "entities": [dict(e) for e in entities],
            "relations": [dict(r) for r in relations],
        }


# ============================================================
# RECHERCHE DES ENTITÉS
# ============================================================

def search_world_entities(
    db: sqlite3.Connection,
    user_id: str,
    query: str,
    entity_type: str | None = None,
    limit: int = 20
) -> list[dict[str, Any]]:
    """
    Recherche des entités dans le modèle du monde.

    La recherche porte sur :
    - L'identifiant.
    - Le type.
    - Les propriétés JSON.
    """

    user_id = _validate_user_id(user_id)

    if not isinstance(query, str):
        raise ValueError(
            "query doit être une chaîne de caractères."
        )

    query = query.strip()

    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH]

    limit = _normalize_limit(limit, 1, 100)

    params: list[Any] = [user_id]

    sql = """
        SELECT *
        FROM world_entities
        WHERE user_id = ?
    """

    if entity_type is not None:
        entity_type = _validate_text(
            entity_type,
            "entity_type",
            MAX_TYPE_LENGTH
        ).casefold()

        sql += " AND entity_type = ?"
        params.append(entity_type)

    if query:
        search_pattern = f"%{_escape_like(query.casefold())}%"

        sql += """
            AND (
                LOWER(id) LIKE ? ESCAPE '\\'
                OR LOWER(entity_type) LIKE ? ESCAPE '\\'
                OR LOWER(properties_json) LIKE ? ESCAPE '\\'
            )
        """

        params.extend([
            search_pattern,
            search_pattern,
            search_pattern
        ])

    sql += """
        ORDER BY last_observed_at DESC
        LIMIT ?
    """

    params.append(limit)

    rows = _fetch_dicts(
        db,
        sql,
        tuple(params)
    )

    results: list[dict[str, Any]] = []

    for item in rows:
        try:
            properties = json.loads(
                item.get("properties_json") or "{}"
            )

            if not isinstance(properties, dict):
                properties = {}

        except (json.JSONDecodeError, TypeError, ValueError):
            properties = {}

        item["properties"] = properties
        item.pop("properties_json", None)

        results.append(item)

    return results


# ============================================================
# STATISTIQUES DU MODÈLE DU MONDE
# ============================================================

def get_world_statistics(
    db: sqlite3.Connection,
    user_id: str
) -> dict[str, Any]:
    """
    Retourne les statistiques du modèle du monde de Chappie.

    Permet notamment de suivre son développement :
    - Nombre d'entités connues.
    - Nombre de relations établies.
    - Répartition des types d'entités.
    - Répartition des sources d'information.
    """

    user_id = _validate_user_id(user_id)

    entity_count = db.execute(
        """
        SELECT COUNT(*)
        FROM world_entities
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    relation_count = db.execute(
        """
        SELECT COUNT(*)
        FROM world_relations
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    entity_types = _fetch_dicts(
        db,
        """
        SELECT
            entity_type,
            COUNT(*) AS count
        FROM world_entities
        WHERE user_id = ?
        GROUP BY entity_type
        ORDER BY count DESC
        """,
        (user_id,)
    )

    sources = _fetch_dicts(
        db,
        """
        SELECT
            source_type,
            COUNT(*) AS count
        FROM world_entities
        WHERE user_id = ?
        GROUP BY source_type
        ORDER BY count DESC
        """,
        (user_id,)
    )

    relation_sources = _fetch_dicts(
        db,
        """
        SELECT
            source_type,
            COUNT(*) AS count
        FROM world_relations
        WHERE user_id = ?
        GROUP BY source_type
        ORDER BY count DESC
        """,
        (user_id,)
    )

    return {
        "entity_count": int(entity_count or 0),
        "relation_count": int(relation_count or 0),
        "entity_types": entity_types,
        "entity_sources": sources,
        "relation_sources": relation_sources,
        "generated_at": utc_now()
    }
