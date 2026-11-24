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
    review_perception_fusion,
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


def _make_fusion_candidate(db, user_id="creator"):
    audio = record_observation(
        db, user_id, "audio", "J'entends le mot pomme.", "confirmed_transcription"
    )
    vision = record_observation(
        db, user_id, "vision", "Une forme rouge arrondie.", "camera_snapshot"
    )
    candidates = link_temporally_cooccurring_observation(
        db, user_id, audio["observation_id"]
    )
    assert len(candidates) == 1
    return candidates[0]["id"]


def test_cross_modal_review_requires_explicit_evidence_and_is_terminal(tmp_path):
    db = open_db(tmp_path / "fusion-review.sqlite3")
    try:
        candidate_id = _make_fusion_candidate(db)
        with pytest.raises(ValueError, match="preuve"):
            review_perception_fusion(db, "creator", candidate_id, "confirm", "  ")

        confirmed = review_perception_fusion(
            db, "creator", candidate_id, "confirm",
            "Le Créateur confirme que la pomme entendue est bien l'objet montré.",
        )
        assert confirmed["status"] == "confirmed"
        assert confirmed["world_knowledge_promoted"] is False
        assert confirmed["evidence"]["human_review"]["decision"] == "confirm"

        with pytest.raises(ValueError, match="déjà été examiné"):
            review_perception_fusion(
                db, "creator", candidate_id, "reject",
                "Tentative de remplacer la décision précédente.",
            )

        persisted = list_perception_fusions(db, "creator")
        assert persisted[0]["status"] == "confirmed"
        assert persisted[0]["evidence"]["human_review"]["decision"] == "confirm"
        # A reviewed co-occurrence remains evidence, not an automatically
        # created entity or learned word-to-image association.
        assert db.execute(
            "SELECT COUNT(*) FROM word_visual_associations"
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_cross_modal_review_isolated_between_users(tmp_path):
    db = open_db(tmp_path / "fusion-review-isolation.sqlite3")
    try:
        candidate_id = _make_fusion_candidate(db)
        with pytest.raises(ValueError, match="introuvable"):
            review_perception_fusion(
                db, "another-user", candidate_id, "confirm",
                "L'autre utilisateur ne peut pas examiner ce candidat.",
            )
        assert list_perception_fusions(db, "creator")[0]["status"] == "candidate"
        assert list_perception_fusions(db, "another-user") == []
    finally:
        db.close()


@pytest.mark.parametrize(
    ("decision", "evidence"),
    [
        ("maybe", "Une décision non prise en charge."),
        ("confirm", ""),
        ("reject", "   "),
        ("reject", "x" * 1001),
        (None, "Une preuve suffisamment détaillée."),
        ("confirm", None),
    ],
)
def test_cross_modal_review_rejects_invalid_decisions_and_evidence(
    tmp_path, decision, evidence
):
    db = open_db(tmp_path / "fusion-review-invalid.sqlite3")
    try:
        candidate_id = _make_fusion_candidate(db)
        with pytest.raises(ValueError):
            review_perception_fusion(
                db, "creator", candidate_id, decision, evidence
            )
        assert list_perception_fusions(db, "creator")[0]["status"] == "candidate"
    finally:
        db.close()
