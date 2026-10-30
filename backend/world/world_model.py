# backend/world/world_model.py

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
        raise ValueError(f"{field_name} doit être une chaîne de caractères.")

    value = value.strip()

    if not value:
        raise ValueError(f"{field_name} est obligatoire.")

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} ne peut pas dépasser {max_length} caractères."
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
        raise ValueError("source_type doit être une chaîne.")

    source_type = source_type.strip().lower()

    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            "source_type invalide. Valeurs autorisées : "
            + ", ".join(sorted(VALID_SOURCE_TYPES))
        )

    return source_type


def _validate_confidence(confidence: float) -> float:
    """Garantit un niveau de confiance compris entre 0 et 1."""

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise ValueError("confidence doit être un nombre.")

    if not math.isfinite(confidence):
        raise ValueError("confidence doit être un nombre fini.")

    return max(0.0, min(1.0, confidence))


def _validate_properties(
    properties: dict[str, Any] | None
) -> dict[str, Any]:
    """Valide et vérifie que les propriétés peuvent être converties en JSON."""

    if properties is None:
        properties = {}

    if not isinstance(properties, dict):
        raise ValueError("Les propriétés doivent être un dictionnaire.")

    try:
        # Vérification de la sérialisation JSON.
        json.dumps(
            properties,
            ensure_ascii=False,
            allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Les propriétés contiennent une valeur non compatible JSON : {exc}"
        ) from exc

    return properties


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    """
    Convertit un résultat SQLite en dictionnaire.

    Compatible avec sqlite3.Row et les connexions qui retournent
    des tuples classiques.
    """

    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return dict(row)

    if isinstance(row, tuple):
        raise TypeError(
            "Impossible de convertir un tuple sans connaître "
            "les noms de colonnes."
        )

    try:
        return dict(row)
    except (TypeError, ValueError):
        raise TypeError("Format de résultat SQLite non pris en charge.")


def _fetch_dict(
    db: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = ()
) -> dict[str, Any] | None:
    """Exécute une requête et convertit le résultat en dictionnaire."""

    cursor = db.execute(query, params)
    row = cursor.fetchone()

    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    columns = [column[0] for column in cursor.description]

    return dict(zip(columns, row))


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

    if isinstance(rows[0], sqlite3.Row):
        return [dict(row) for row in rows]

    columns = [column[0] for column in cursor.description]

    return [
        dict(zip(columns, row))
        for row in rows
    ]


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

    db.executescript("""
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

        UNIQUE(user_id, subject_id, predicate, object_id)
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
    """)

    db.commit()


# ============================================================
# CRÉATION / MISE À JOUR DES ENTITÉS
# ============================================================

def upsert_world_entity(
    db: sqlite3.Connection,
    user_id: str,
    entity_id: str,
    entity_type: str,
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

    try:
        # Vérification de la propriété de l'identifiant.
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

        db.execute("""
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

        """, (
            entity_id,
            user_id,
            entity_type,
            props_json,
            source_type,
            confidence,
            now
        ))

        db.commit()

    except Exception:
        db.rollback()
        raise

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
            item.get("properties_json", "{}")
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
    predicate: str,
    object_id: str,
    source_type: str = "observed",
    confidence: float = 0.8
) -> dict[str, Any]:
    """
    Crée ou met à jour une relation orientée :

        Sujet -> Prédicat -> Objet

    Exemple :

        Chappie -> connaît -> Julien
        Julien -> possède -> voiture
        voiture -> située_dans -> garage

    Les deux entités doivent exister et appartenir au même utilisateur.
    """

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

    try:
        # Vérifie que le sujet appartient bien à l'utilisateur.
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

        # Vérifie que l'objet appartient bien à l'utilisateur.
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

        db.execute("""
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
        """, (
            user_id,
            subject_id,
            predicate,
            object_id,
            source_type,
            confidence,
            now
        ))

        db.commit()

    except Exception:
        db.rollback()
        raise

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
    db: sqlite3.Connection,
    user_id: str,
    entity_id: str
) -> list[dict[str, Any]]:
    """
    Récupère toutes les relations dans lesquelles une entité apparaît.

    L'entité peut être :
    - Le sujet de la relation.
    - L'objet de la relation.

    Exemple :

        Chappie -> connaît -> Julien
        Julien -> possède -> voiture

    Si entity_id correspond à Julien, les deux relations sont retournées.
    """

    user_id = _validate_user_id(user_id)

    entity_id = _validate_text(
        entity_id,
        "entity_id",
        MAX_ID_LENGTH
    )

    rows = _fetch_dicts(
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

    return rows


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

    Cette fonction est complémentaire aux fonctions existantes.
    """

    user_id = _validate_user_id(user_id)

    query = _validate_text(
        query,
        "query",
        500
    ).casefold()

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit doit être un nombre entier.")

    limit = max(1, min(100, limit))

    params: list[Any] = [user_id]

    sql = """
        SELECT *
        FROM world_entities
        WHERE user_id = ?
    """

    if entity_type:
        entity_type = _validate_text(
            entity_type,
            "entity_type",
            MAX_TYPE_LENGTH
        ).casefold()

        sql += " AND entity_type = ?"
        params.append(entity_type)

    sql += """
        AND (
            LOWER(id) LIKE ?
            OR LOWER(entity_type) LIKE ?
            OR LOWER(properties_json) LIKE ?
        )
        ORDER BY last_observed_at DESC
        LIMIT ?
    """

    search_pattern = f"%{query}%"

    params.extend([
        search_pattern,
        search_pattern,
        search_pattern,
        limit
    ])

    rows = _fetch_dicts(
        db,
        sql,
        tuple(params)
    )

    results = []

    for item in rows:
        try:
            properties = json.loads(
                item.get("properties_json", "{}")
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
        "entity_count": entity_count,
        "relation_count": relation_count,
        "entity_types": entity_types,
        "entity_sources": sources,
        "relation_sources": relation_sources,
        "generated_at": utc_now()
    }



