"""V24 — Cross-modal perception linking.

Links nearby audio and vision observations as reviewable co-occurrence candidates.
A temporal match is NOT treated as proof that both senses refer to the same object.
Only explicit teaching/validation may promote a candidate into learned knowledge.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_WINDOW_SECONDS = 300
DEFAULT_WINDOW_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_perception_fusion_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS perception_fusion_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            audio_observation_id TEXT NOT NULL,
            vision_observation_id TEXT NOT NULL,
            time_delta_seconds REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate'
                CHECK(status IN ('candidate','confirmed','rejected')),
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, audio_observation_id, vision_observation_id),
            FOREIGN KEY(audio_observation_id)
                REFERENCES sensory_observations(observation_id) ON DELETE CASCADE,
            FOREIGN KEY(vision_observation_id)
                REFERENCES sensory_observations(observation_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_perception_fusion_user
            ON perception_fusion_candidates(user_id, created_at DESC);
    """)


def link_temporally_cooccurring_observation(
    db: sqlite3.Connection,
    user_id: str,
    observation_id: str,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[dict[str, Any]]:
    """Create cautious cross-modal candidates around one new observation."""
    window = max(1, min(int(window_seconds), MAX_WINDOW_SECONDS))
    current = db.execute(
        """SELECT observation_id, modality, content, created_at
           FROM sensory_observations
           WHERE observation_id=? AND user_id=?""",
        (observation_id, user_id),
    ).fetchone()
    if current is None:
        raise ValueError("Observation sensorielle introuvable.")
    if current["modality"] not in {"audio", "vision"}:
        return []

    try:
        current_time = datetime.fromisoformat(current["created_at"])
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return []

    lower = (current_time - timedelta(seconds=window)).isoformat()
    upper = (current_time + timedelta(seconds=window)).isoformat()
    other_modality = "vision" if current["modality"] == "audio" else "audio"
    rows = db.execute(
        """SELECT observation_id, modality, content, created_at
           FROM sensory_observations
           WHERE user_id=? AND modality=? AND created_at BETWEEN ? AND ?
             AND observation_id<>?
           ORDER BY created_at DESC LIMIT 20""",
        (user_id, other_modality, lower, upper, observation_id),
    ).fetchall()

    created = []
    for other in rows:
        try:
            other_time = datetime.fromisoformat(other["created_at"])
            if other_time.tzinfo is None:
                other_time = other_time.replace(tzinfo=timezone.utc)
            delta = abs((current_time - other_time).total_seconds())
        except (TypeError, ValueError):
            continue
        if delta > window:
            continue
        audio_id = observation_id if current["modality"] == "audio" else other["observation_id"]
        vision_id = observation_id if current["modality"] == "vision" else other["observation_id"]
        evidence = {
            "rule": "temporal_cooccurrence_only",
            "warning": "Temporal proximity does not prove semantic identity.",
            "audio_excerpt": (current["content"] if current["modality"] == "audio" else other["content"])[:500],
            "vision_excerpt": (current["content"] if current["modality"] == "vision" else other["content"])[:500],
        }
        db.execute(
            """INSERT OR IGNORE INTO perception_fusion_candidates
               (user_id,audio_observation_id,vision_observation_id,
                time_delta_seconds,status,evidence_json,created_at)
               VALUES (?,?,?,?, 'candidate', ?, ?)""",
            (user_id, audio_id, vision_id, delta,
             json.dumps(evidence, ensure_ascii=False), _now().isoformat()),
        )
        created.append({
            "audio_observation_id": audio_id,
            "vision_observation_id": vision_id,
            "time_delta_seconds": round(delta, 3),
            "status": "candidate",
            "requires_validation": True,
        })
    return created


def list_perception_fusions(
    db: sqlite3.Connection, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT id,audio_observation_id,vision_observation_id,
                  time_delta_seconds,status,evidence_json,created_at
           FROM perception_fusion_candidates
           WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        except (TypeError, ValueError):
            item["evidence"] = {}
        result.append(item)
    return result



def review_perception_fusion(
    db: sqlite3.Connection,
    user_id: str,
    candidate_id: int,
    decision: str,
    evidence: str,
) -> dict[str, Any]:
    """Record an explicit human review without promoting a candidate to world knowledge."""
    if isinstance(candidate_id, bool):
        raise ValueError("Identifiant de rapprochement invalide.")
    try:
        candidate_id = int(candidate_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Identifiant de rapprochement invalide.") from exc
    if candidate_id < 1:
        raise ValueError("Identifiant de rapprochement invalide.")

    decision = str(decision or "").strip().casefold()
    if decision not in {"confirm", "reject"}:
        raise ValueError("La décision doit être confirm ou reject.")

    evidence = str(evidence or "").strip()
    if not evidence or len(evidence) > 1000:
        raise ValueError("Une preuve de validation (1 à 1000 caractères) est obligatoire.")

    row = db.execute(
        """SELECT id, status, evidence_json
           FROM perception_fusion_candidates
           WHERE id=? AND user_id=?""",
        (candidate_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Candidat de rapprochement introuvable.")

    if row["status"] != "candidate":
        raise ValueError("Ce candidat a déjà été examiné et ne peut plus être modifié.")

    try:
        stored_evidence = json.loads(row["evidence_json"] or "{}")
        if not isinstance(stored_evidence, dict):
            stored_evidence = {}
    except (TypeError, ValueError):
        stored_evidence = {}

    reviewed_at = _now().isoformat()
    stored_evidence["human_review"] = {
        "decision": decision,
        "evidence": evidence,
        "reviewed_at": reviewed_at,
    }
    status = "confirmed" if decision == "confirm" else "rejected"
    cursor = db.execute(
        """UPDATE perception_fusion_candidates
           SET status=?, evidence_json=?
           WHERE id=? AND user_id=? AND status='candidate'""",
        (
            status,
            json.dumps(stored_evidence, ensure_ascii=False, allow_nan=False),
            candidate_id,
            user_id,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("Le candidat a été examiné entre-temps.")

    return {
        "id": candidate_id,
        "status": status,
        "evidence": stored_evidence,
        "world_knowledge_promoted": False,
    }
