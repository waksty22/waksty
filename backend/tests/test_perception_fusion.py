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



@pytest.mark.parametrize("window_seconds", [0, -1, -300])
def test_temporal_fusion_rejects_non_positive_window(db, window_seconds):
    _, vision = make_audio_and_vision(db)
    with pytest.raises(ValueError, match="fenêtre temporelle"):
        link_temporally_cooccurring_observation(
            db, "creator", vision["observation_id"],
            window_seconds=window_seconds,
        )
    assert db.execute(
        "SELECT COUNT(*) FROM perception_fusion_candidates"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_listing_fusions_rejects_non_positive_limit(db, limit):
    with pytest.raises(ValueError, match="limite"):
        list_perception_fusions(db, "creator", limit=limit)


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


def test_temporal_fusion_compares_instants_across_timezone_offsets(db):
    audio, vision = make_audio_and_vision(db)
    # These values describe instants one minute apart, despite different
    # textual offsets. Lexicographic ISO comparison incorrectly excludes audio.
    db.execute(
        "UPDATE sensory_observations SET created_at=? WHERE observation_id=?",
        ("2026-11-26T10:01:00+00:00", audio["observation_id"]),
    )
    db.execute(
        "UPDATE sensory_observations SET created_at=? WHERE observation_id=?",
        ("2026-11-26T12:00:00+02:00", vision["observation_id"]),
    )

    result = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"], window_seconds=120
    )

    assert len(result) == 1
    assert result[0]["audio_observation_id"] == audio["observation_id"]
    assert result[0]["vision_observation_id"] == vision["observation_id"]
    assert result[0]["time_delta_seconds"] == 60.0


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


def test_technical_camera_receipt_never_creates_a_semantic_fusion_candidate(db):
    audio = record_observation(
        db, "creator", "audio", "Que vois-tu ?", "microphone"
    )
    receipt = record_observation(
        db,
        "creator",
        "vision",
        "Le serveur a reçu une trame caméra.",
        "live_camera_frame_received_by_server",
        confidence=0.0,
        metadata={"image_bytes_persisted": False, "semantic_analysis_performed": False},
    )

    assert link_temporally_cooccurring_observation(
        db, "creator", audio["observation_id"]
    ) == []
    assert link_temporally_cooccurring_observation(
        db, "creator", receipt["observation_id"]
    ) == []
    assert list_perception_fusions(db, "creator") == []


def test_temporal_fusion_preserves_subsecond_window_and_timezone_order(db):
    audio, vision = make_audio_and_vision(db)
    # The observations are 0.8 seconds apart, but their textual offsets differ.
    db.execute(
        "UPDATE sensory_observations SET created_at=? WHERE observation_id=?",
        ("2026-11-26T09:00:00.100+02:00", audio["observation_id"]),
    )
    db.execute(
        "UPDATE sensory_observations SET created_at=? WHERE observation_id=?",
        ("2026-11-26T07:00:00.900Z", vision["observation_id"]),
    )

    result = link_temporally_cooccurring_observation(
        db, "creator", vision["observation_id"], window_seconds=1
    )

    assert len(result) == 1
    assert result[0]["audio_observation_id"] == audio["observation_id"]
    assert result[0]["vision_observation_id"] == vision["observation_id"]
    assert result[0]["time_delta_seconds"] == pytest.approx(0.8)


def test_fusion_listing_orders_mixed_timezone_timestamps_by_instant(db):
    audio, vision = make_audio_and_vision(db)
    db.execute(
        "INSERT INTO perception_fusion_candidates "
        "(user_id,audio_observation_id,vision_observation_id,time_delta_seconds,status,evidence_json,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("creator", audio["observation_id"], vision["observation_id"], 0.1, "candidate", "{}", "2026-11-26T09:00:00.100+02:00"),
    )
    db.execute(
        "INSERT INTO sensory_observations "
        "(observation_id,user_id,modality,content,source,confidence,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("audio-later", "creator", "audio", "Son ultérieur", "microphone", 0.9, "{}", "2026-11-26T07:00:00.900Z"),
    )
    db.execute(
        "INSERT INTO sensory_observations "
        "(observation_id,user_id,modality,content,source,confidence,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("vision-later", "creator", "vision", "Image ultérieure", "camera", 0.9, "{}", "2026-11-26T07:00:00.900Z"),
    )
    db.execute(
        "INSERT INTO perception_fusion_candidates "
        "(user_id,audio_observation_id,vision_observation_id,time_delta_seconds,status,evidence_json,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("creator", "audio-later", "vision-later", 0.1, "candidate", "{}", "2026-11-26T07:00:00.900Z"),
    )

    listed = list_perception_fusions(db, "creator")

    assert listed[0]["audio_observation_id"] == "audio-later"
    assert listed[1]["audio_observation_id"] == audio["observation_id"]
