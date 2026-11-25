"""Explicitly promote owner-confirmed audio/vision links into world knowledge."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from world.world_model import (
    add_world_relation,
    upsert_world_entity,
)


def _stable_entity_id(user_id: str, kind: str, value: str) -> str:
    digest = hashlib.sha256(
        (user_id + "\\0" + value).encode("utf-8")
    ).hexdigest()[:32]
    return f"{kind}:{digest}"


def promote_confirmed_perception_fusion(
    db: sqlite3.Connection,
    user_id: str,
    candidate_id: int,
    object_label: str,
    evidence: str,
) -> dict[str, Any]:
    """Create durable semantic links only after explicit review and naming."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    if isinstance(candidate_id, bool) or not isinstance(candidate_id, int) or candidate_id < 1:
        raise ValueError("Identifiant de rapprochement invalide.")
    if not isinstance(object_label, str):
        raise ValueError("Le nom de l'objet est obligatoire.")
    object_label = object_label.strip()
    if not object_label or len(object_label) > 120:
        raise ValueError("Le nom de l'objet doit contenir entre 1 et 120 caractères.")
    if not isinstance(evidence, str):
        raise ValueError("Une preuve explicite est obligatoire.")
    evidence = evidence.strip()
    if not evidence or len(evidence) > 1000:
        raise ValueError("La preuve doit contenir entre 1 et 1000 caractères.")

    candidate = db.execute(
        """SELECT id, status, audio_observation_id, vision_observation_id, evidence_json
           FROM perception_fusion_candidates WHERE id=? AND user_id=?""",
        (candidate_id, user_id),
    ).fetchone()
    if candidate is None:
        raise ValueError("Candidat de rapprochement introuvable.")
    if candidate["status"] != "confirmed":
        raise ValueError("Le rapprochement doit d'abord être confirmé explicitement.")
    try:
        stored_evidence = json.loads(candidate["evidence_json"] or "{}")
    except (TypeError, ValueError):
        stored_evidence = {}
    if not isinstance(stored_evidence, dict):
        stored_evidence = {}
    review = stored_evidence.get("human_review")
    if not isinstance(review, dict) or review.get("decision") != "confirm":
        raise ValueError("La confirmation humaine est absente ou invalide.")
    existing_promotion = stored_evidence.get("semantic_promotion")
    if isinstance(existing_promotion, dict) and existing_promotion.get("promoted") is True:
        raise ValueError("Ce rapprochement a déjà été transformé en apprentissage.")

    observations = db.execute(
        """SELECT observation_id, modality, content, source
           FROM sensory_observations
           WHERE user_id=? AND observation_id IN (?, ?)""",
        (user_id, candidate["audio_observation_id"], candidate["vision_observation_id"]),
    ).fetchall()
    by_modality = {row["modality"]: row for row in observations}
    if set(by_modality) != {"audio", "vision"} or len(observations) != 2:
        raise ValueError("Les deux observations audio et vision ne sont plus disponibles.")
    if any(row["source"] == "live_camera_frame_received_by_server" for row in observations):
        raise ValueError("Une réception technique de caméra ne peut pas devenir un fait appris.")

    object_id = _stable_entity_id(user_id, "object", object_label.casefold())
    upsert_world_entity(
        db, user_id, object_id, "object",
        {
            "label": object_label,
            "learned_from_perception_fusion": candidate_id,
            "audio_observation_id": candidate["audio_observation_id"],
            "vision_observation_id": candidate["vision_observation_id"],
            "confirmation_evidence": evidence,
        },
        source_type="confirmed", confidence=1.0,
    )

    relation_ids = []
    for modality in ("audio", "vision"):
        observation = by_modality[modality]
        observation_id = observation["observation_id"]
        observation_entity_id = _stable_entity_id(
            user_id, "sensory-observation", observation_id
        )
        upsert_world_entity(
            db, user_id, observation_entity_id, "sensory_observation",
            {
                "observation_id": observation_id,
                "modality": modality,
                "excerpt": str(observation["content"] or "")[:500],
                "source": str(observation["source"] or "")[:100],
            },
            source_type="observed", confidence=0.8,
        )
        relation = add_world_relation(
            db, user_id, object_id, observation_entity_id,
            relation_type=f"confirmed_by_{modality}_observation",
            source_type="confirmed", confidence=1.0,
        )
        relation_ids.append(relation["id"])

    stored_evidence["semantic_promotion"] = {
        "object_label": object_label,
        "object_entity_id": object_id,
        "audio_observation_id": candidate["audio_observation_id"],
        "vision_observation_id": candidate["vision_observation_id"],
        "relation_ids": relation_ids,
        "evidence": evidence,
        "promoted": True,
    }
    db.execute(
        """UPDATE perception_fusion_candidates SET evidence_json=?
           WHERE id=? AND user_id=? AND status='confirmed'""",
        (json.dumps(stored_evidence, ensure_ascii=False, allow_nan=False), candidate_id, user_id),
    )
    return {
        "candidate_id": candidate_id,
        "object_label": object_label,
        "object_entity_id": object_id,
        "relation_ids": relation_ids,
        "semantic_identity_proven": True,
        "world_knowledge_promoted": True,
    }
