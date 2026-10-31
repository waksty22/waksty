
"""
Chappie V19.3 — curriculum cognitif et apprentissage progressif.

Fonctionnalités :
- Gestion des paliers de développement.
- Évaluation des compétences par des tests réels.
- Suivi de la réussite et de la maturité cognitive.
- Progression persistante par utilisateur.
- Conservation des jalons déjà acquis.

La maturité cognitive ne constitue pas une mesure scientifique
de l'intelligence ou de la conscience. Elle représente un indicateur
interne de progression du système Chappie.
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

MAX_USER_ID_LENGTH = 80
MAX_TEST_NAME_LENGTH = 120
MAX_DETAILS_LENGTH = 20000

MIN_SCORE = 0.0
MAX_SCORE = 100.0

MIN_SUCCESS_RATE = 0.5


DEFAULT_STAGES = [
    ("Nouveau-né (Éveil)", 1.0),
    ("Enfant (Apprenti)", 3.0),
    ("Adolescent (Explorateur)", 5.0),
    ("Adulte (Complice)", 8.0),
]


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def utc_now() -> str:
    """Renvoie la date actuelle au format ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _validate_text(
    value: str,
    field_name: str,
    max_length: int
) -> str:
    """Valide une chaîne de caractères."""

    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} doit être du texte."
        )

    value = value.strip()

    if not value:
        raise ValueError(
            f"{field_name} ne peut pas être vide."
        )

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} dépasse {max_length} caractères."
        )

    return value


def _validate_user_id(user_id: str) -> str:
    """Valide l'identifiant utilisateur."""

    return _validate_text(
        user_id,
        "user_id",
        MAX_USER_ID_LENGTH
    )


def _validate_score(score: float) -> float:
    """Valide un score compris entre 0 et 100."""

    if isinstance(score, bool):
        raise ValueError(
            "Le score doit être un nombre."
        )

    try:
        score = float(score)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Le score doit être un nombre."
        ) from exc

    if not math.isfinite(score):
        raise ValueError(
            "Le score doit être une valeur finie."
        )

    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(
            "Le score doit être compris entre 0 et 100."
        )

    return score


def _validate_maturity(current_maturity: float) -> float:
    """Valide la maturité cognitive."""

    if isinstance(current_maturity, bool):
        raise ValueError(
            "La maturité cognitive doit être un nombre."
        )

    try:
        value = float(current_maturity)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "La maturité cognitive doit être un nombre."
        ) from exc

    if not math.isfinite(value):
        raise ValueError(
            "La maturité cognitive doit être une valeur finie."
        )

    if value < 0:
        raise ValueError(
            "La maturité cognitive ne peut pas être négative."
        )

    return value


def _validate_details(
    details: dict[str, Any] | None
) -> dict[str, Any]:
    """Valide les détails et leur compatibilité JSON."""

    if details is None:
        return {}

    if not isinstance(details, dict):
        raise ValueError(
            "Les détails du test doivent être un dictionnaire."
        )

    try:
        serialized = json.dumps(
            details,
            ensure_ascii=False,
            allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Les détails ne sont pas compatibles JSON : {exc}"
        ) from exc

    if len(serialized) > MAX_DETAILS_LENGTH:
        raise ValueError(
            "Les détails du test sont trop volumineux."
        )

    return details


def _row_to_dict(
    row: Any,
    cursor: sqlite3.Cursor
) -> dict[str, Any] | None:
    """Convertit un résultat SQLite en dictionnaire."""

    if row is None:
        return None

    if isinstance(row, sqlite3.Row):
        return dict(row)

    if isinstance(row, dict):
        return dict(row)

    columns = [
        description[0]
        for description in (cursor.description or [])
    ]

    return dict(zip(columns, row))


def _table_exists(
    db: sqlite3.Connection,
    table_name: str
) -> bool:
    """Vérifie l'existence d'une table SQLite."""

    result = db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,)
    ).fetchone()

    return result is not None


def _ensure_user_stages(
    db: sqlite3.Connection,
    user_id: str
) -> None:
    """
    Initialise les jalons d'un utilisateur.

    INSERT OR IGNORE garantit que les paliers déjà présents
    et leur progression ne sont pas écrasés.
    """

    for stage_name, min_maturity in DEFAULT_STAGES:
        initial_status = (
            "achieved"
            if min_maturity <= 1.0
            else "locked"
        )

        db.execute(
            """
            INSERT OR IGNORE INTO cognitive_milestones (
                user_id,
                stage_name,
                min_maturity,
                status,
                achieved_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                stage_name,
                min_maturity,
                initial_status,
                utc_now() if initial_status == "achieved" else None
            )
        )


# ============================================================
# INITIALISATION DES TABLES
# ============================================================

def init_learning_tables(
    db: sqlite3.Connection
) -> None:
    """Initialise les tables du curriculum cognitif."""

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cognitive_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT NOT NULL,

            stage_name TEXT NOT NULL,

            min_maturity REAL NOT NULL
                CHECK(min_maturity >= 0),

            status TEXT NOT NULL
                CHECK(
                    status IN (
                        'locked',
                        'in_progress',
                        'achieved'
                    )
                )
                DEFAULT 'locked',

            achieved_at TEXT,

            UNIQUE(user_id, stage_name)
        );

        CREATE TABLE IF NOT EXISTS competency_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT NOT NULL,

            test_name TEXT NOT NULL,

            passed INTEGER NOT NULL DEFAULT 0
                CHECK(passed IN (0, 1)),

            score REAL NOT NULL DEFAULT 0.0
                CHECK(score BETWEEN 0 AND 100),

            details TEXT NOT NULL DEFAULT '{}',

            tested_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_milestones_user
            ON cognitive_milestones(user_id);

        CREATE INDEX IF NOT EXISTS idx_competency_tests_user
            ON competency_tests(user_id, tested_at DESC);

        CREATE INDEX IF NOT EXISTS idx_competency_tests_name
            ON competency_tests(user_id, test_name);
        """
    )

    # Initialise les paliers uniquement si la table skills existe.
    # Cela évite de bloquer Chappie lorsque les modules sont initialisés
    # dans un ordre différent.
    if _table_exists(db, "skills"):
        columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(skills)"
            ).fetchall()
        }

        if "user_id" in columns:
            users = db.execute(
                """
                SELECT DISTINCT user_id
                FROM skills
                WHERE user_id IS NOT NULL
                  AND TRIM(user_id) != ''
                """
            ).fetchall()

            for row in users:
                user_id = (
                    row["user_id"]
                    if isinstance(row, sqlite3.Row)
                    else row[0]
                )

                _ensure_user_stages(
                    db,
                    str(user_id)
                )


# ============================================================
# ENREGISTREMENT DES TESTS DE COMPÉTENCES
# ============================================================

def evaluate_competency_test(
    db: sqlite3.Connection,
    user_id: str,
    test_name: str,
    passed: bool,
    score: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Enregistre le résultat d'un test de compétence de Chappie.

    Le test doit représenter une réussite réelle et mesurable.

    La réussite n'est pas déduite automatiquement du score :
    le paramètre passed reste la décision du moteur de test.
    """

    user_id = _validate_user_id(user_id)

    test_name = _validate_text(
        test_name,
        "test_name",
        MAX_TEST_NAME_LENGTH
    )

    if not isinstance(passed, bool):
        raise ValueError(
            "passed doit être un booléen."
        )

    score = _validate_score(score)
    details = _validate_details(details)

    now = utc_now()

    details_json = json.dumps(
        details,
        ensure_ascii=False,
        allow_nan=False
    )

    db.execute(
        """
        INSERT INTO competency_tests (
            user_id,
            test_name,
            passed,
            score,
            details,
            tested_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            test_name,
            1 if passed else 0,
            score,
            details_json,
            now
        )
    )

    return {
        "test_name": test_name,
        "passed": passed,
        "score": score,
        "details": details,
        "tested_at": now
    }


# ============================================================
# ÉVALUATION DES JALONS COGNITIFS
# ============================================================

def update_cognitive_milestones(
    db: sqlite3.Connection,
    user_id: str,
    current_maturity: float
) -> list[dict[str, Any]]:
    """
    Met à jour les jalons de développement de Chappie.

    Conditions :
    - Le premier palier est acquis automatiquement.
    - Les autres paliers nécessitent une maturité suffisante.
    - Au moins un test doit avoir été réalisé.
    - Le taux de réussite global doit atteindre 50 %.

    Les paliers déjà acquis restent acquis.
    """

    user_id = _validate_user_id(user_id)

    current_maturity = _validate_maturity(
        current_maturity
    )

    # Assure la présence des jalons même si l'utilisateur
    # n'avait encore aucune compétence dans la table skills.
    _ensure_user_stages(
        db,
        user_id
    )

    # Récupération des résultats des tests.
    cursor = db.execute(
        """
        SELECT
            COUNT(*) AS total_tests,
            COALESCE(AVG(passed), 0.0) AS success_rate
        FROM competency_tests
        WHERE user_id = ?
        """,
        (user_id,)
    )

    test_stats = _row_to_dict(
        cursor.fetchone(),
        cursor
    ) or {}

    total_tests = int(
        test_stats.get("total_tests") or 0
    )

    success_rate = float(
        test_stats.get("success_rate") or 0.0
    )

    # Récupération des jalons.
    cursor = db.execute(
        """
        SELECT
            id,
            stage_name,
            min_maturity,
            status,
            achieved_at
        FROM cognitive_milestones
        WHERE user_id = ?
        ORDER BY min_maturity ASC, id ASC
        """,
        (user_id,)
    )

    milestones = [
        _row_to_dict(row, cursor)
        for row in cursor.fetchall()
    ]

    updated_milestones: list[dict[str, Any]] = []

    now = utc_now()

    for milestone in milestones:
        milestone_id = int(milestone["id"])

        stage_name = milestone["stage_name"]
        min_maturity = float(milestone["min_maturity"])
        status = milestone["status"]
        achieved_at = milestone.get("achieved_at")

        new_status = status

        # Le premier stade est acquis automatiquement.
        can_achieve = min_maturity <= 1.0

        # Les stades suivants exigent une maturité suffisante
        # et une réussite réelle aux tests.
        if min_maturity > 1.0:
            can_achieve = (
                current_maturity >= min_maturity
                and total_tests > 0
                and success_rate >= MIN_SUCCESS_RATE
            )

        if status != "achieved":
            if can_achieve:
                new_status = "achieved"
                achieved_at = achieved_at or now

            elif current_maturity >= min_maturity:
                new_status = "in_progress"

            else:
                new_status = "locked"

            if (
                new_status != status
                or achieved_at != milestone.get("achieved_at")
            ):
                db.execute(
                    """
                    UPDATE cognitive_milestones
                    SET status = ?,
                        achieved_at = ?
                    WHERE id = ?
                      AND user_id = ?
                    """,
                    (
                        new_status,
                        achieved_at,
                        milestone_id,
                        user_id
                    )
                )

        updated_milestones.append(
            {
                "stage_name": stage_name,
                "min_maturity": min_maturity,
                "status": new_status,
                "achieved_at": achieved_at
            }
        )

    return updated_milestones


# ============================================================
# HISTORIQUE DES TESTS
# ============================================================

def get_competency_test_history(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = 20
) -> list[dict[str, Any]]:
    """
    Retourne l'historique des tests de compétences.

    Fonction complémentaire permettant à l'interface Chappie
    d'afficher la progression réelle des évaluations.
    """

    user_id = _validate_user_id(user_id)
    limit = _normalize_limit(limit, 1, 100)

    cursor = db.execute(
        """
        SELECT
            id,
            user_id,
            test_name,
            passed,
            score,
            details,
            tested_at
        FROM competency_tests
        WHERE user_id = ?
        ORDER BY tested_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit)
    )

    results: list[dict[str, Any]] = []

    for row in cursor.fetchall():
        item = _row_to_dict(row, cursor)

        try:
            details = json.loads(
                item.get("details") or "{}"
            )

            if not isinstance(details, dict):
                details = {}

        except (json.JSONDecodeError, TypeError, ValueError):
            details = {}

        item["details"] = details
        item["passed"] = bool(item["passed"])

        results.append(item)

    return results


# ============================================================
# STATISTIQUES DU CURRICULUM
# ============================================================

def get_learning_statistics(
    db: sqlite3.Connection,
    user_id: str
) -> dict[str, Any]:
    """
    Retourne les statistiques d'apprentissage de Chappie.

    Inclut :
    - Nombre de tests réalisés.
    - Nombre de tests réussis.
    - Taux de réussite.
    - Score moyen.
    - Nombre de paliers acquis.
    - Nombre de paliers en cours.
    - Nombre de paliers verrouillés.
    """

    user_id = _validate_user_id(user_id)

    cursor = db.execute(
        """
        SELECT
            COUNT(*) AS total_tests,

            COALESCE(SUM(passed), 0) AS passed_tests,

            COALESCE(AVG(passed), 0.0) AS success_rate,

            COALESCE(AVG(score), 0.0) AS average_score,

            COALESCE(MAX(score), 0.0) AS best_score

        FROM competency_tests
        WHERE user_id = ?
        """,
        (user_id,)
    )

    test_stats = _row_to_dict(
        cursor.fetchone(),
        cursor
    ) or {}

    cursor = db.execute(
        """
        SELECT
            status,
            COUNT(*) AS count
        FROM cognitive_milestones
        WHERE user_id = ?
        GROUP BY status
        """,
        (user_id,)
    )

    milestone_counts = {
        "achieved": 0,
        "in_progress": 0,
        "locked": 0
    }

    for row in cursor.fetchall():
        item = _row_to_dict(row, cursor)

        status = item["status"]

        if status in milestone_counts:
            milestone_counts[status] = int(item["count"])

    total_tests = int(
        test_stats.get("total_tests") or 0
    )

    passed_tests = int(
        test_stats.get("passed_tests") or 0
    )

    return {
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": total_tests - passed_tests,

        "success_rate": round(
            float(test_stats.get("success_rate") or 0.0),
            3
        ),

        "success_percentage": round(
            float(test_stats.get("success_rate") or 0.0) * 100,
            1
        ),

        "average_score": round(
            float(test_stats.get("average_score") or 0.0),
            2
        ),

        "best_score": round(
            float(test_stats.get("best_score") or 0.0),
            2
        ),

        "milestones": milestone_counts,

        "generated_at": utc_now()
    }
