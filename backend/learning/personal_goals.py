"""Supervised personal learning goals backed by Chappie's existing goals tables.

Suggestions are read-only. A goal is persisted only after the supervisor
explicitly adopts it through the authenticated goals API.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from learning.causal_learning import suggest_supervised_learning_agenda

MAX_GOALS = 10
MAX_EVIDENCE = 2000


def _clean_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} doit être du texte.")
    value = value.strip()
    if not value or len(value) > limit:
        raise ValueError(f"{field} est vide ou trop long.")
    return value


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def suggest_personal_learning_goals(
    db: sqlite3.Connection, user_id: str, limit: int = 5
) -> dict[str, Any]:
    """Derive measurable goal proposals without writing any database row."""
    limit = max(1, min(int(limit), MAX_GOALS))
    agenda = suggest_supervised_learning_agenda(db, user_id, limit=limit)
    existing = db.execute(
        "SELECT title FROM goals WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 100",
        (user_id,),
    ).fetchall()
    active_titles = {_normalize(str(row["title"])) for row in existing}
    proposals: list[dict[str, Any]] = []

    for item in agenda.get("agenda", []):
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        kind = item.get("kind")
        if kind == "review_hypothesis":
            title = f"Clarifier une hypothèse : {topic}"[:300]
            steps = [
                "Reformuler l'hypothèse et préciser ce qui pourrait la contredire.",
                "Définir un critère observable permettant de distinguer les résultats possibles.",
                "Examiner les preuves avec le Créateur et décider si une simulation sûre est utile.",
            ]
            criterion = "Les trois étapes sont documentées avec des éléments vérifiables ; aucune hypothèse n'est déclarée vraie par défaut."
        elif kind == "observation_to_understand":
            title = f"Comprendre une observation : {topic}"[:300]
            steps = [
                "Décrire l'observation et son contexte sans ajouter d'information supposée.",
                "Lister explicitement les éléments connus et les inconnues.",
                "Décider avec le Créateur si une question vérifiable mérite d'être formulée.",
            ]
            criterion = "L'observation, ses inconnues et la décision du Créateur sont documentées."
        else:
            continue
        if _normalize(title) in active_titles:
            continue
        proposals.append({
            "source_kind": str(kind),
            "source_id": int(item.get("source_id", 0)),
            "topic": topic[:240],
            "title": title,
            "reason": str(item.get("reason") or "")[:500],
            "priority": item.get("priority", "low"),
            "criterion": criterion,
            "steps": steps,
            "requires_supervisor_approval": True,
            "persisted": False,
        })

    return {
        "proposals": proposals[:limit],
        "read_only": True,
        "goals_created": 0,
        "user_scoped": True,
        "approval_required": True,
    }


def list_personal_learning_goals(
    db: sqlite3.Connection, user_id: str, limit: int = 30
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT id, title, status, progress, created_at, updated_at
           FROM goals WHERE user_id=? ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    goals: list[dict[str, Any]] = []
    for row in rows:
        goal = dict(row)
        steps = db.execute(
            """SELECT id, description, status, evidence, updated_at
               FROM goal_steps WHERE goal_id=? ORDER BY id ASC""",
            (goal["id"],),
        ).fetchall()
        goal["steps"] = [dict(step) for step in steps]
        goal["progress"] = float(goal.get("progress") or 0.0)
        goals.append(goal)
    return {"goals": goals, "user_scoped": True, "read_only": True}


def record_personal_goal_step(
    db: sqlite3.Connection,
    user_id: str,
    goal_id: int,
    step_id: int,
    evidence: str,
    completed: bool = True,
) -> dict[str, Any]:
    """Record evidence for one step, verifying ownership through the parent goal."""
    if not isinstance(completed, bool):
        raise ValueError("completed doit être un booléen.")
    evidence = _clean_text(evidence, "Preuve", MAX_EVIDENCE)
    row = db.execute(
        """SELECT s.id, s.goal_id FROM goal_steps s
           JOIN goals g ON g.id=s.goal_id
           WHERE s.id=? AND s.goal_id=? AND g.user_id=?""",
        (step_id, goal_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Étape introuvable pour cet utilisateur.")
    status = "completed" if completed else "pending"
    db.execute(
        """UPDATE goal_steps SET status=?, evidence=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=? AND goal_id=?""",
        (status, evidence, step_id, goal_id),
    )
    stats = db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='completed' AND length(trim(evidence))>0
                           THEN 1 ELSE 0 END) AS done
           FROM goal_steps WHERE goal_id=?""",
        (goal_id,),
    ).fetchone()
    total = int(stats["total"] or 0)
    done = int(stats["done"] or 0)
    progress = 100.0 * done / total if total else 0.0
    goal_status = "completed" if total > 0 and done == total else "active"
    db.execute(
        """UPDATE goals SET progress=?, status=?, updated_at=CURRENT_TIMESTAMP
           WHERE id=? AND user_id=?""",
        (progress, goal_status, goal_id, user_id),
    )
    db.commit()
    return {
        "goal_id": goal_id,
        "step_id": step_id,
        "step_status": status,
        "progress": progress,
        "goal_status": goal_status,
        "evidence_recorded": True,
    }
