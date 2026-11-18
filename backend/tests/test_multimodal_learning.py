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
    list_perception_fusions,
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


@pytest.mark.parametrize(
    "confidence",
    [None, "not-a-number", float("inf"), float("nan"), True, False],
)
def test_sensory_observation_rejects_invalid_confidence_without_writing(
    tmp_path, confidence
):
    db = open_db(tmp_path / "invalid-confidence.sqlite3")
    try:
        with pytest.raises(ValueError, match="Confiance|confiance"):
            record_observation(
                db, "creator", "vision", "forme rouge", "camera",
                confidence=confidence,
            )
        assert db.execute(
            "SELECT COUNT(*) FROM sensory_observations"
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_visual_association_requires_nonempty_validation_evidence(tmp_path):
    db = open_db(tmp_path / "validation-evidence.sqlite3")
    try:
        record_heard_word(db, "creator", "pomme")
        advance_word(db, "creator", "pomme", "imitated")
        observation = record_observation(
            db, "creator", "vision", "forme rouge", "camera"
        )
        with pytest.raises(ValueError, match="validation visuelle"):
            associate_word_with_observation(
                db, "creator", "pomme", observation["observation_id"], evidence="   "
            )
        assert db.execute(
            "SELECT COUNT(*) FROM word_visual_associations"
        ).fetchone()[0] == 0
        association = associate_word_with_observation(
            db, "creator", "pomme", observation["observation_id"],
            evidence="Le Créateur confirme que l'image montre une pomme.",
        )
        assert association["association_saved"] is True
    finally:
        db.close()


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
                db, "another-user", "coq", observation["observation_id"], "Test d’isolation utilisateur"
            )
        with pytest.raises(ValueError):
            associate_word_with_observation(
                db, "creator", "inconnu", observation["observation_id"], "Test de mot inconnu"
            )
    finally:
        db.close()


@pytest.mark.parametrize("invalid_content", [None, 7, True, {}, []])
def test_sensory_observation_rejects_non_text_content_without_writing(
    tmp_path, invalid_content
):
    db = open_db(tmp_path / "invalid-content.sqlite3")
    try:
        with pytest.raises(ValueError, match="contenu|texte"):
            record_observation(
                db, "creator", "vision", invalid_content, "camera"
            )
        assert db.execute(
            "SELECT COUNT(*) FROM sensory_observations"
        ).fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize("invalid_window", [None, "120", 1.5, True, False, {}])
def test_perception_fusion_rejects_non_integer_window(tmp_path, invalid_window):
    db = open_db(tmp_path / "invalid-window.sqlite3")
    try:
        audio = record_observation(
            db, "creator", "audio", "bonjour", "confirmed_transcription"
        )
        with pytest.raises(ValueError, match="fenêtre|entier"):
            link_temporally_cooccurring_observation(
                db, "creator", audio["observation_id"],
                window_seconds=invalid_window,
            )
        assert db.execute(
            "SELECT COUNT(*) FROM perception_fusion_candidates"
        ).fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize("invalid_limit", [None, "10", 1.5, True, False, {}])
def test_perception_fusion_list_rejects_non_integer_limit(tmp_path, invalid_limit):
    db = open_db(tmp_path / "invalid-limit.sqlite3")
    try:
        with pytest.raises(ValueError, match="limite|entier"):
            list_perception_fusions(db, "creator", limit=invalid_limit)
    finally:
        db.close()


@pytest.mark.parametrize("invalid_user_id", [None, 7, True, {}, [], "   "])
def test_perception_fusion_rejects_invalid_user_identity(tmp_path, invalid_user_id):
    db = open_db(tmp_path / "invalid-fusion-user.sqlite3")
    try:
        audio = record_observation(
            db, "creator", "audio", "bonjour", "confirmed_transcription"
        )
        with pytest.raises(ValueError, match="Identifiant utilisateur"):
            link_temporally_cooccurring_observation(
                db, invalid_user_id, audio["observation_id"]
            )
        with pytest.raises(ValueError, match="Identifiant utilisateur"):
            list_perception_fusions(db, invalid_user_id)
        assert db.execute(
            "SELECT COUNT(*) FROM perception_fusion_candidates"
        ).fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize("invalid_observation_id", [None, 7, True, {}, [], "   "])
def test_perception_fusion_rejects_invalid_observation_identity(
    tmp_path, invalid_observation_id
):
    db = open_db(tmp_path / "invalid-fusion-observation.sqlite3")
    try:
        with pytest.raises(ValueError, match="Identifiant d’observation"):
            link_temporally_cooccurring_observation(
                db, "creator", invalid_observation_id
            )
        assert db.execute(
            "SELECT COUNT(*) FROM perception_fusion_candidates"
        ).fetchone()[0] == 0
    finally:
        db.close()
