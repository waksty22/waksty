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
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError("Identifiant d’observation invalide.")
    if isinstance(window_seconds, bool) or not isinstance(window_seconds, int):
        raise ValueError("La fenêtre temporelle doit être un entier.")
    if window_seconds < 1:
        raise ValueError("La fenêtre temporelle doit être au moins égale à une seconde.")
    window = min(window_seconds, MAX_WINDOW_SECONDS)
    current = db.execute(
        """SELECT observation_id, modality, content, source, created_at
           FROM sensory_observations
           WHERE observation_id=? AND user_id=?""",
        (observation_id, user_id),
    ).fetchone()
    if current is None:
        raise ValueError("Observation sensorielle introuvable.")
    if current["modality"] not in {"audio", "vision"}:
        return []
    # A server-side camera receipt proves only that bytes reached this backend.
    # It is not visual content and must never become an audio/vision match.
    if current["source"] == "live_camera_frame_received_by_server":
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
        """SELECT observation_id, modality, content, source, created_at
           FROM sensory_observations
           WHERE user_id=? AND modality=?
             AND julianday(created_at) BETWEEN julianday(?) - (1.0 / 86400.0)
                                           AND julianday(?) + (1.0 / 86400.0)
             AND observation_id<>?
           ORDER BY julianday(created_at) DESC LIMIT 20""",
        (user_id, other_modality, lower, upper, observation_id),
    ).fetchall()

    created = []
    for other in rows:
        if other["source"] == "live_camera_frame_received_by_server":
            continue
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
        cursor = db.execute(
            """INSERT OR IGNORE INTO perception_fusion_candidates
               (user_id,audio_observation_id,vision_observation_id,
                time_delta_seconds,status,evidence_json,created_at)
               VALUES (?,?,?,?, 'candidate', ?, ?)""",
            (user_id, audio_id, vision_id, delta,
             json.dumps(evidence, ensure_ascii=False), _now().isoformat()),
        )
        persisted = db.execute(
            """SELECT id, status, time_delta_seconds
               FROM perception_fusion_candidates
               WHERE user_id=? AND audio_observation_id=?
                 AND vision_observation_id=?""",
            (user_id, audio_id, vision_id),
        ).fetchone()
        if persisted is None:
            # Defensive fail-closed path: never report a candidate that was
            # not actually persisted.
            continue
        created.append({
            "id": persisted["id"],
            "audio_observation_id": audio_id,
            "vision_observation_id": vision_id,
            # Replays must describe the persisted candidate, not a newly
            # computed temporal delta that may differ from the original.
            "time_delta_seconds": round(float(persisted["time_delta_seconds"]), 3),
            "status": persisted["status"],
            "created": cursor.rowcount == 1,
            "requires_validation": persisted["status"] == "candidate",
        })
    return created


def list_perception_fusions(
    db: sqlite3.Connection, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("La limite doit être un entier.")
    if limit < 1:
        raise ValueError("La limite doit être un entier positif.")
    limit = min(limit, 100)
    rows = db.execute(
        """SELECT id,audio_observation_id,vision_observation_id,
                  time_delta_seconds,status,evidence_json,created_at
           FROM perception_fusion_candidates
           WHERE user_id=? ORDER BY COALESCE(julianday(created_at), -1.0) DESC, id DESC LIMIT ?""",
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
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if (
        isinstance(candidate_id, bool)
        or not isinstance(candidate_id, int)
        or candidate_id < 1
    ):
        raise ValueError("Identifiant de rapprochement invalide.")

    if not isinstance(decision, str):
        raise ValueError("La décision doit être confirm ou reject.")
    decision = decision.strip().casefold()
    if decision not in {"confirm", "reject"}:
        raise ValueError("La décision doit être confirm ou reject.")

    if not isinstance(evidence, str):
        raise ValueError("Une preuve de validation (1 à 1000 caractères) est obligatoire.")
    evidence = evidence.strip()
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
