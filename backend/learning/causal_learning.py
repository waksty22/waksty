"""Supervised causal learning for Chappie.

Stores observations, hypotheses, controlled experiments and outcomes separately.
No physical action is executed by this module: an experiment is only recorded
after an explicit supervisor approval and must be performed externally.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

MAX_TEXT = 2000
ALLOWED_ENVIRONMENTS = {"simulation", "controlled_safe"}
ALLOWED_RESULTS = {"supported", "contradicted", "inconclusive"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} doit être du texte.")
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(f"{field} est vide ou trop long.")
    return value


def _confidence(value: Any, field: str = "Confiance") -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} invalide.") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field} doit être comprise entre 0 et 1.")
    return value


def init_causal_learning_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS causal_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK(source_type IN ('observed','taught')),
            evidence TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_causal_obs_user
            ON causal_observations(user_id, id DESC);

        CREATE TABLE IF NOT EXISTS causal_hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            observation_id INTEGER NOT NULL REFERENCES causal_observations(id),
            statement TEXT NOT NULL,
            predicted_effect TEXT NOT NULL,
            confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
            status TEXT NOT NULL DEFAULT 'proposed'
                CHECK(status IN ('proposed','testing','supported','contradicted','uncertain')),
            evidence_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_causal_hyp_user
            ON causal_hypotheses(user_id, id DESC);

        CREATE TABLE IF NOT EXISTS causal_experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            hypothesis_id INTEGER NOT NULL REFERENCES causal_hypotheses(id),
            environment TEXT NOT NULL CHECK(environment IN ('simulation','controlled_safe')),
            procedure TEXT NOT NULL,
            prediction TEXT NOT NULL,
            supervisor_approved INTEGER NOT NULL CHECK(supervisor_approved = 1),
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN ('planned','completed','cancelled')),
            result TEXT NOT NULL DEFAULT '',
            evaluation TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_causal_exp_user
            ON causal_experiments(user_id, id DESC);
    """)


def record_observation(
    db: sqlite3.Connection, user_id: str, event: str, outcome: str,
    context: str = "", source_type: str = "observed",
    evidence: str = "", confidence: float = 0.7,
) -> dict[str, Any]:
    if source_type not in {"observed", "taught"}:
        raise ValueError("Une observation doit provenir d'une observation ou d'un enseignement.")
    now = _now()
    values = (
        user_id, _text(event, "Événement"), _text(context, "Contexte", 1000) if context else "",
        _text(outcome, "Résultat"), source_type, str(evidence or "").strip()[:1000],
        _confidence(confidence), now,
    )
    cur = db.execute(
        """INSERT INTO causal_observations
           (user_id,event,context,outcome,source_type,evidence,confidence,created_at)
           VALUES (?,?,?,?,?,?,?,?)""", values
    )
    db.commit()
    return {"id": cur.lastrowid, "event": values[1], "context": values[2],
            "outcome": values[3], "source_type": source_type,
            "evidence": values[5], "confidence": values[6], "created_at": now}


def propose_hypothesis(
    db: sqlite3.Connection, user_id: str, observation_id: int,
    statement: str, predicted_effect: str, confidence: float = 0.3,
) -> dict[str, Any]:
    observation = db.execute(
        "SELECT id FROM causal_observations WHERE id=? AND user_id=?",
        (observation_id, user_id),
    ).fetchone()
    if observation is None:
        raise ValueError("Observation introuvable pour cet utilisateur.")
    now = _now()
    statement = _text(statement, "Hypothèse")
    predicted_effect = _text(predicted_effect, "Effet prédit")
    confidence = _confidence(confidence)
    cur = db.execute(
        """INSERT INTO causal_hypotheses
           (user_id,observation_id,statement,predicted_effect,confidence,status,created_at,updated_at)
           VALUES (?,?,?,?,?,'proposed',?,?)""",
        (user_id, observation_id, statement, predicted_effect, confidence, now, now),
    )
    db.commit()
    return {"id": cur.lastrowid, "observation_id": observation_id,
            "statement": statement, "predicted_effect": predicted_effect,
            "confidence": confidence, "status": "proposed"}


def plan_experiment(
    db: sqlite3.Connection, user_id: str, hypothesis_id: int,
    environment: str, procedure: str, prediction: str,
    supervisor_approved: bool,
) -> dict[str, Any]:
    if supervisor_approved is not True:
        raise ValueError("Une approbation explicite du superviseur est obligatoire.")
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ValueError("Environnement interdit : utiliser une simulation ou un cadre contrôlé sûr.")
    hypothesis = db.execute(
        "SELECT id FROM causal_hypotheses WHERE id=? AND user_id=?",
        (hypothesis_id, user_id),
    ).fetchone()
    if hypothesis is None:
        raise ValueError("Hypothèse introuvable pour cet utilisateur.")
    procedure = _text(procedure, "Protocole")
    prediction = _text(prediction, "Prédiction")
    now = _now()
    cur = db.execute(
        """INSERT INTO causal_experiments
           (user_id,hypothesis_id,environment,procedure,prediction,supervisor_approved,status,created_at)
           VALUES (?,?,?,?,?,1,'planned',?)""",
        (user_id, hypothesis_id, environment, procedure, prediction, now),
    )
    db.execute(
        "UPDATE causal_hypotheses SET status='testing', updated_at=? WHERE id=? AND user_id=?",
        (now, hypothesis_id, user_id),
    )
    db.commit()
    return {"id": cur.lastrowid, "hypothesis_id": hypothesis_id,
            "environment": environment, "procedure": procedure,
            "prediction": prediction, "supervisor_approved": True, "status": "planned"}


def evaluate_experiment(
    db: sqlite3.Connection, user_id: str, experiment_id: int,
    observed_result: str, evaluation: str,
) -> dict[str, Any]:
    row = db.execute(
        """SELECT e.*, h.confidence, h.id AS hid
           FROM causal_experiments e JOIN causal_hypotheses h ON h.id=e.hypothesis_id
           WHERE e.id=? AND e.user_id=? AND h.user_id=?""",
        (experiment_id, user_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Expérience introuvable pour cet utilisateur.")
    if row["status"] != "planned":
        raise ValueError("Cette expérience a déjà été clôturée.")
    observed_result = _text(observed_result, "Résultat observé")
    evaluation = evaluation.strip().lower() if isinstance(evaluation, str) else ""
    if evaluation not in ALLOWED_RESULTS:
        raise ValueError("Évaluation attendue : supported, contradicted ou inconclusive.")
    prior = float(row["confidence"])
    if evaluation == "supported":
        updated = min(0.98, prior + (1.0 - prior) * 0.25)
        hypothesis_status = "supported"
    elif evaluation == "contradicted":
        updated = max(0.02, prior * 0.5)
        hypothesis_status = "contradicted"
    else:
        updated = prior
        hypothesis_status = "uncertain"
    now = _now()
    db.execute(
        """UPDATE causal_experiments SET status='completed', result=?, evaluation=?, completed_at=?
           WHERE id=? AND user_id=?""",
        (observed_result, evaluation, now, experiment_id, user_id),
    )
    db.execute(
        """UPDATE causal_hypotheses SET confidence=?, status=?, evidence_count=evidence_count+1,
           updated_at=? WHERE id=? AND user_id=?""",
        (updated, hypothesis_status, now, row["hid"], user_id),
    )
    db.commit()
    return {"experiment_id": experiment_id, "hypothesis_id": row["hid"],
            "observed_result": observed_result, "evaluation": evaluation,
            "previous_confidence": prior, "confidence": updated,
            "status": hypothesis_status}



def review_causal_learning(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Return an append-only view of experiment outcomes for each hypothesis.

    Completed experiments remain the evidence trail. The aggregate assessment
    is descriptive only: mixed results stay mixed, and the current confidence
    field is explicitly not presented as a calibrated probability. This
    function is read-only and never rewrites hypotheses or experiment records.
    """
    limit = max(1, min(int(limit), 50))
    hypotheses = db.execute(
        """
        SELECT id, observation_id, statement, predicted_effect,
               confidence, status, evidence_count, created_at, updated_at
        FROM causal_hypotheses
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    reviewed: list[dict[str, Any]] = []
    for hypothesis_row in hypotheses:
        hypothesis = dict(hypothesis_row)
        experiments = db.execute(
            """
            SELECT id, environment, procedure, prediction, status, result,
                   evaluation, created_at, completed_at
            FROM causal_experiments
            WHERE user_id=? AND hypothesis_id=?
            ORDER BY id ASC
            LIMIT 200
            """,
            (user_id, int(hypothesis["id"])),
        ).fetchall()
        history = [dict(row) for row in experiments]
        counts = {
            key: sum(1 for item in history
                     if item["status"] == "completed" and item["evaluation"] == key)
            for key in ALLOWED_RESULTS
        }
        if counts["supported"] and counts["contradicted"]:
            assessment = "mixed_evidence"
        elif counts["contradicted"]:
            assessment = "challenged_by_recorded_tests"
        elif counts["supported"]:
            assessment = "supported_by_recorded_tests"
        elif counts["inconclusive"]:
            assessment = "inconclusive"
        elif any(item["status"] == "planned" for item in history):
            assessment = "awaiting_evaluation"
        else:
            assessment = "not_tested"

        hypothesis["evaluation_history"] = history
        hypothesis["evidence_counts"] = counts
        hypothesis["evidence_assessment"] = assessment
        hypothesis["confidence_note"] = (
            "Score interne ajusté par les évaluations successives ; "
            "ce n'est pas une probabilité calibrée ni une certitude."
        )
        reviewed.append(hypothesis)

    return {
        "hypotheses": reviewed,
        "read_only": True,
        "history_is_preserved": True,
        "mixed_evidence_remains_mixed": True,
        "assessment_is_not_proof": True,
    }


def list_causal_learning(db: sqlite3.Connection, user_id: str) -> dict[str, list[dict[str, Any]]]:
    observations = [dict(r) for r in db.execute(
        "SELECT * FROM causal_observations WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)
    ).fetchall()]
    hypotheses = [dict(r) for r in db.execute(
        "SELECT * FROM causal_hypotheses WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)
    ).fetchall()]
    experiments = [dict(r) for r in db.execute(
        "SELECT * FROM causal_experiments WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)
    ).fetchall()]
    return {"observations": observations, "hypotheses": hypotheses, "experiments": experiments}
