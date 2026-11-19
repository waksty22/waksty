from __future__ import annotations

import sqlite3

import pytest

from learning.sensory import init_sensory_tables, record_observation
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    list_perception_fusions,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    init_sensory_tables(connection)
    init_perception_fusion_tables(connection)
    yield connection
    connection.close()


def make_audio_and_vision(db):
    audio = record_observation(
        db, "creator", "audio", "J'entends un bruit.", "microphone"
    )
    vision = record_observation(
        db, "creator", "vision", "Je vois un objet.", "camera"
    )
    return audio, vision


def test_temporal_fusion_is_only_a_candidate_and_reports_persisted_state(db):
    audio, vision = make_audio_and_vision(db)

    result = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"]
    )

    assert len(result) == 1
    assert result[0]["audio_observation_id"] == audio["observation_id"]
    assert result[0]["vision_observation_id"] == vision["observation_id"]
    assert result[0]["status"] == "candidate"
    assert result[0]["created"] is True
    assert result[0]["requires_validation"] is True
    assert list_perception_fusions(db, "creator")[0]["status"] == "candidate"


def test_reprocessing_does_not_resurrect_a_rejected_fusion(db):
    _, vision = make_audio_and_vision(db)
    first = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"]
    )
    assert first[0]["status"] == "candidate"

    db.execute(
        "UPDATE perception_fusion_candidates SET status='rejected' WHERE id=?",
        (first[0]["id"],),
    )

    replay = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"]
    )

    assert len(replay) == 1
    assert replay[0]["id"] == first[0]["id"]
    assert replay[0]["status"] == "rejected"
    assert replay[0]["created"] is False
    assert replay[0]["requires_validation"] is False
    assert list_perception_fusions(db, "creator")[0]["status"] == "rejected"


def test_replayed_fusion_reports_original_persisted_time_delta(db):
    _, vision = make_audio_and_vision(db)
    first = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"]
    )
    fusion_id = first[0]["id"]
    db.execute(
        "UPDATE perception_fusion_candidates SET time_delta_seconds=42.125 WHERE id=?",
        (fusion_id,),
    )

    replay = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"]
    )

    assert replay[0]["id"] == fusion_id
    assert replay[0]["created"] is False
    assert replay[0]["time_delta_seconds"] == 42.125


def test_temporal_fusion_never_links_observations_across_users(db):
    record_observation(
        db, "alice", "audio", "Son privé.", "microphone"
    )
    vision = record_observation(
        db, "bob", "vision", "Image privée.", "camera"
    )

    result = link_temporally_cooccurring_observation(
        db, "bob", vision["observation_id"]
    )

    assert result == []
    assert list_perception_fusions(db, "bob") == []
