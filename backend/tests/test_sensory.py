import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import init_language_tables, record_heard_word, advance_word
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    review_perception_fusion,
)
from world.world_model import init_world_tables
from learning.sensory import (
    init_sensory_tables,
    record_observation,
    associate_word_with_observation,
    list_observations,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_language_tables(connection)
    init_sensory_tables(connection)
    init_perception_fusion_tables(connection)
    yield connection
    connection.close()


def test_audio_observation_is_persisted_without_claiming_understanding(db):
    from learning.language import record_heard_text

    heard_text = "Regarde la montre"
    record_heard_text(db, "creator", heard_text)
    record_observation(
        db, "creator", "audio", heard_text,
        "gemini_live_transcription", confidence=0.7,
    )
    observations = list_observations(db, "creator")
    assert {item["modality"] for item in observations} == {"audio"}
    rows = db.execute(
        "SELECT word, state FROM personal_vocabulary ORDER BY word"
    ).fetchall()
    assert {row["word"]: row["state"] for row in rows} == {
        "regarde": "heard",
        "la": "heard",
        "montre": "heard",
    }


def test_visual_association_requires_imitation_then_recognizes_word(db):
    record_heard_word(db, "creator", "coq")
    observation = record_observation(
        db, "creator", "vision", "Un animal à plumes dans l'image.",
        "camera_snapshot", confidence=0.45,
    )
    with pytest.raises(ValueError):
        associate_word_with_observation(
            db, "creator", "coq", observation["observation_id"]
        )

    advance_word(db, "creator", "coq", "imitated")
    result = associate_word_with_observation(
        db, "creator", "coq", observation["observation_id"]
    )
    assert result["vocabulary_state"] == "recognized"
    row = db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    assert row["state"] == "recognized"


def test_observations_are_isolated_by_user(db):
    observation = record_observation(
        db, "creator", "vision", "Objet rouge", "camera_snapshot"
    )
    with pytest.raises(ValueError):
        associate_word_with_observation(
            db, "other", "objet", observation["observation_id"]
        )



def _fusion_candidate(db, user_id="creator"):
    visual = record_observation(
        db, user_id, "vision", "Une pomme rouge.", "camera_snapshot"
    )
    audio = record_observation(
        db, user_id, "audio", "Regarde la pomme.", "gemini_live"
    )
    candidates = link_temporally_cooccurring_observation(
        db, user_id, audio["observation_id"]
    )
    assert len(candidates) == 1
    row = db.execute(
        """SELECT id FROM perception_fusion_candidates
           WHERE user_id=? AND audio_observation_id=? AND vision_observation_id=?""",
        (user_id, audio["observation_id"], visual["observation_id"]),
    ).fetchone()
    return int(row["id"])


def test_explicit_fusion_review_records_decision_without_promoting_knowledge(db):
    init_world_tables(db)
    candidate_id = _fusion_candidate(db)
    reviewed = review_perception_fusion(
        db, "creator", candidate_id, "confirm",
        "Le créateur confirme que le mot pomme désigne l'objet visible.",
    )

    assert reviewed["status"] == "confirmed"
    assert reviewed["world_knowledge_promoted"] is False
    row = db.execute(
        "SELECT status, evidence_json FROM perception_fusion_candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    assert row["status"] == "confirmed"
    assert '"decision": "confirm"' in row["evidence_json"]
    assert db.execute(
        "SELECT COUNT(*) FROM world_entities"
    ).fetchone()[0] == 0


def test_fusion_review_is_user_scoped_and_terminal(db):
    candidate_id = _fusion_candidate(db)

    with pytest.raises(ValueError):
        review_perception_fusion(
            db, "other-user", candidate_id, "confirm",
            "Validation explicite par le créateur.",
        )

    rejected = review_perception_fusion(
        db, "creator", candidate_id, "reject",
        "La phrase ne décrit pas l'objet affiché.",
    )
    assert rejected["status"] == "rejected"

    with pytest.raises(ValueError):
        review_perception_fusion(
            db, "creator", candidate_id, "confirm",
            "Nouvelle validation contradictoire.",
        )


@pytest.mark.parametrize(
    ("decision", "evidence"),
    [("maybe", "preuve"), ("confirm", ""), ("reject", "x" * 1001)],
)
def test_fusion_review_rejects_invalid_decisions_or_evidence(db, decision, evidence):
    candidate_id = _fusion_candidate(db)
    with pytest.raises(ValueError):
        review_perception_fusion(
            db, "creator", candidate_id, decision, evidence
        )
