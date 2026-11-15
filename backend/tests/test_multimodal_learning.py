"""Cross-modal learning must wait for explicit semantic validation."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import init_language_tables, record_heard_word, advance_word
from learning.sensory import (
    init_sensory_tables,
    record_observation,
    associate_word_with_observation,
)
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
)


def open_db(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_language_tables(db)
    init_sensory_tables(db)
    init_perception_fusion_tables(db)
    return db


def test_audio_vision_cooccurrence_is_only_a_candidate_until_validated(tmp_path):
    path = tmp_path / "multimodal-learning.sqlite3"
    db = open_db(path)
    try:
        record_heard_word(db, "creator", "pomme", "Mot entendu")
        advance_word(db, "creator", "pomme", "imitated")

        audio = record_observation(
            db, "creator", "audio", "pomme",
            "confirmed_transcription", confidence=0.8,
        )
        vision = record_observation(
            db, "creator", "vision", "forme rouge arrondie",
            "camera_snapshot", confidence=0.45,
        )
        candidates = link_temporally_cooccurring_observation(
            db, "creator", audio["observation_id"]
        )
        assert len(candidates) == 1
        assert candidates[0]["status"] == "candidate"
        assert candidates[0]["requires_validation"] is True

        # A time-nearby audio and image must not create semantic identity.
        count = db.execute(
            "SELECT COUNT(*) FROM word_visual_associations"
        ).fetchone()[0]
        assert count == 0

        # Only explicit validation links the word to this image.
        association = associate_word_with_observation(
            db, "creator", "pomme", vision["observation_id"],
            evidence="Le Créateur confirme que l'image montre une pomme.",
        )
        assert association["association_saved"] is True
        assert association["vocabulary_state"] == "recognized"
        db.commit()
    finally:
        db.close()

    # The validated link survives a full connection restart.
    reopened = open_db(path)
    try:
        row = reopened.execute(
            """SELECT word, observation_id, evidence
               FROM word_visual_associations WHERE user_id=?""",
            ("creator",),
        ).fetchone()
        assert row is not None
        assert row["word"] == "pomme"
        assert row["observation_id"] == vision["observation_id"]
        assert "confirme" in row["evidence"].casefold()
        assert reopened.execute(
            "SELECT COUNT(*) FROM word_visual_associations WHERE user_id=?",
            ("another-user",),
        ).fetchone()[0] == 0
    finally:
        reopened.close()


def test_visual_association_rejects_unknown_or_other_users_observations(tmp_path):
    db = open_db(tmp_path / "isolation.sqlite3")
    try:
        record_heard_word(db, "creator", "coq")
        advance_word(db, "creator", "coq", "imitated")
        observation = record_observation(
            db, "creator", "vision", "un animal rouge", "camera"
        )
        with pytest.raises(ValueError):
            associate_word_with_observation(
                db, "another-user", "coq", observation["observation_id"]
            )
        with pytest.raises(ValueError):
            associate_word_with_observation(
                db, "creator", "inconnu", observation["observation_id"]
            )
    finally:
        db.close()
