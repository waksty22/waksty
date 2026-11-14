import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import init_language_tables, record_heard_word, advance_word
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    list_perception_fusions,
)
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



def test_merged_live_turn_creates_one_audio_observation_and_reviewable_fusion(db):
    init_perception_fusion_tables(db)
    visual = record_observation(
        db, "creator", "vision", "Une pomme rouge sur une table.",
        "camera_snapshot", confidence=0.45,
    )
    merged_audio = record_observation(
        db, "creator", "audio", "Regarde la pomme sur la table.",
        "gemini_live_completed_turn", confidence=0.8,
    )

    candidates = link_temporally_cooccurring_observation(
        db, "creator", merged_audio["observation_id"]
    )
    saved_audio = list_observations(db, "creator")
    fusions = list_perception_fusions(db, "creator")

    assert len([item for item in saved_audio if item["modality"] == "audio"]) == 1
    assert candidates == [{
        "audio_observation_id": merged_audio["observation_id"],
        "vision_observation_id": visual["observation_id"],
        "time_delta_seconds": candidates[0]["time_delta_seconds"],
        "status": "candidate",
        "requires_validation": True,
    }]
    assert len(fusions) == 1
    assert fusions[0]["status"] == "candidate"
    assert fusions[0]["evidence"]["rule"] == "temporal_cooccurrence_only"
