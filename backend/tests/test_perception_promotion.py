from __future__ import annotations

import sqlite3

import pytest

from learning.sensory import init_sensory_tables, record_observation
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    review_perception_fusion,
)
from learning.perception_promotion import promote_confirmed_perception_fusion
from world.world_model import init_world_tables


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    init_sensory_tables(connection)
    init_perception_fusion_tables(connection)
    init_world_tables(connection)
    yield connection
    connection.close()


def make_confirmed_candidate(db, user_id="creator"):
    audio = record_observation(db, user_id, "audio", "J'entends le mot tasse.", "microphone")
    vision = record_observation(db, user_id, "vision", "Une tasse blanche sur la table.", "camera")
    link_temporally_cooccurring_observation(db, user_id, vision["observation_id"])
    candidate_id = db.execute(
        "SELECT id FROM perception_fusion_candidates WHERE user_id=?",
        (user_id,),
    ).fetchone()["id"]
    review_perception_fusion(
        db, user_id, candidate_id, "confirm",
        "Le créateur confirme explicitement que le mot entendu désigne la tasse visible.",
    )
    return candidate_id, audio, vision


def test_explicitly_confirmed_fusion_promotes_named_object_and_both_senses(db):
    candidate_id, audio, vision = make_confirmed_candidate(db)

    result = promote_confirmed_perception_fusion(
        db, "creator", candidate_id, "tasse",
        "J'ai confirmé que le son « tasse » désigne l'objet visible.",
    )

    assert result["semantic_identity_proven"] is True
    assert result["world_knowledge_promoted"] is True
    assert len(result["relation_ids"]) == 2
    entity = db.execute(
        "SELECT * FROM world_entities WHERE id=? AND user_id='creator'",
        (result["object_entity_id"],),
    ).fetchone()
    assert entity["source_type"] == "confirmed"
    assert entity["confidence"] == 1.0
    relations = db.execute(
        "SELECT predicate, source_type, confidence FROM world_relations "
        "WHERE user_id='creator' AND subject_id=?",
        (result["object_entity_id"],),
    ).fetchall()
    assert {row["predicate"] for row in relations} == {
        "confirmed_by_audio_observation",
        "confirmed_by_vision_observation",
    }
    assert all(row["source_type"] == "confirmed" and row["confidence"] == 1.0 for row in relations)
    stored = db.execute(
        "SELECT evidence_json FROM perception_fusion_candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    assert '"promoted": true' in stored["evidence_json"]
    assert audio["observation_id"] in stored["evidence_json"]
    assert vision["observation_id"] in stored["evidence_json"]


def test_temporal_candidate_cannot_be_promoted_without_human_confirmation(db):
    audio = record_observation(db, "creator", "audio", "tasse", "microphone")
    vision = record_observation(db, "creator", "vision", "une tasse", "camera")
    result = link_temporally_cooccurring_observation(db, "creator", vision["observation_id"])
    with pytest.raises(ValueError, match="confirmé explicitement"):
        promote_confirmed_perception_fusion(db, "creator", result[0]["id"], "tasse", "preuve")
    assert db.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0] == 0


def test_rejected_fusion_cannot_be_promoted(db):
    audio = record_observation(db, "creator", "audio", "tasse", "microphone")
    vision = record_observation(db, "creator", "vision", "une tasse", "camera")
    result = link_temporally_cooccurring_observation(db, "creator", vision["observation_id"])
    review_perception_fusion(db, "creator", result[0]["id"], "reject", "Ce n'est pas le même objet.")
    with pytest.raises(ValueError, match="confirmé explicitement"):
        promote_confirmed_perception_fusion(db, "creator", result[0]["id"], "tasse", "preuve")


def test_promotion_is_user_scoped_and_does_not_expose_another_users_candidate(db):
    candidate_id, _, _ = make_confirmed_candidate(db, "alice")
    with pytest.raises(ValueError, match="introuvable"):
        promote_confirmed_perception_fusion(db, "bob", candidate_id, "tasse", "preuve")
    assert db.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("label", "proof"),
    [("", "preuve"), ("x" * 121, "preuve"), ("tasse", ""), ("tasse", "x" * 1001)],
)
def test_promotion_rejects_invalid_label_or_evidence(db, label, proof):
    candidate_id, _, _ = make_confirmed_candidate(db)
    with pytest.raises(ValueError):
        promote_confirmed_perception_fusion(db, "creator", candidate_id, label, proof)
    assert db.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0] == 0
