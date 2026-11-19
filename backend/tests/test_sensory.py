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
            db, "creator", "coq", observation["observation_id"], "Test de validation visuelle explicite"
        )

    advance_word(db, "creator", "coq", "imitated")
    result = associate_word_with_observation(
        db, "creator", "coq", observation["observation_id"],
        "Le créateur confirme que le mot coq correspond à l’observation visuelle.",
    )
    assert result["vocabulary_state"] == "recognized"
    row = db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    assert row["state"] == "recognized"


@pytest.mark.parametrize("invalid_evidence", [None, 7, True, {}, [], "   ", "x" * 501])
def test_visual_association_rejects_non_text_or_blank_evidence(db, invalid_evidence):
    record_heard_word(db, "creator", "coq")
    advance_word(db, "creator", "coq", "imitated")
    observation = record_observation(
        db, "creator", "vision", "Un animal à plumes.", "camera_snapshot"
    )
    with pytest.raises(ValueError, match="preuve|validation visuelle"):
        associate_word_with_observation(
            db, "creator", "coq", observation["observation_id"], invalid_evidence
        )


def test_visual_recognition_preserves_imitation_evidence_and_stores_visual_proof(db):
    record_heard_word(db, "creator", "coq", "Exposition initiale")
    advance_word(
        db, "creator", "coq", "imitated",
        evidence="Chappie a imité le mot coq à voix haute.",
    )
    observation = record_observation(
        db, "creator", "vision", "Un coq dans le jardin.",
        "camera_snapshot", confidence=0.45,
    )

    result = associate_word_with_observation(
        db, "creator", "coq", observation["observation_id"],
        "Le créateur confirme que l'image représente un coq.",
    )

    vocabulary = db.execute(
        "SELECT state, evidence FROM personal_vocabulary WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    association = db.execute(
        """SELECT evidence FROM word_visual_associations
           WHERE user_id=? AND word=? AND observation_id=?""",
        ("creator", "coq", observation["observation_id"]),
    ).fetchone()

    assert result["vocabulary_state"] == "recognized"
    assert vocabulary["state"] == "recognized"
    assert vocabulary["evidence"] == "Chappie a imité le mot coq à voix haute."
    assert association["evidence"] == "Le créateur confirme que l'image représente un coq."


def test_observations_are_isolated_by_user(db):
    observation = record_observation(
        db, "creator", "vision", "Objet rouge", "camera_snapshot"
    )
    with pytest.raises(ValueError):
        associate_word_with_observation(
            db, "other", "objet", observation["observation_id"], "Test d’isolation utilisateur"
        )


@pytest.mark.parametrize("invalid_modality", [None, 7, True, {}, []])
def test_observation_rejects_invalid_modality_without_writing(db, invalid_modality):
    with pytest.raises(ValueError, match="Modalité"):
        record_observation(
            db, "creator", invalid_modality, "Un son", "microphone"
        )
    assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_source", [None, 7, True, {}, [], "", "x" * 81])
def test_observation_rejects_invalid_source_without_writing(db, invalid_source):
    with pytest.raises(ValueError, match="source"):
        record_observation(
            db, "creator", "audio", "Un son", invalid_source
        )
    assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_metadata", [[], "texte", 7, True, float("nan"), {"x": float("inf")}])
def test_observation_rejects_invalid_metadata_without_writing(db, invalid_metadata):
    with pytest.raises(ValueError, match="métadonnées"):
        record_observation(
            db, "creator", "vision", "Objet", "camera", metadata=invalid_metadata
        )
    assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_user_id", [None, 7, True, {}, [], "   "])
def test_list_observations_rejects_invalid_user_identity(db, invalid_user_id):
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        list_observations(db, invalid_user_id)


@pytest.mark.parametrize("invalid_limit", [None, "10", 1.5, True, False, 0, -1, {}])
def test_list_observations_rejects_invalid_limit(db, invalid_limit):
    with pytest.raises(ValueError, match="limite"):
        list_observations(db, "creator", invalid_limit)


def test_list_observations_returns_object_for_malformed_or_non_object_metadata(db):
    observation = record_observation(
        db, "creator", "vision", "Objet", "camera"
    )
    db.execute(
        "UPDATE sensory_observations SET metadata_json='[]' WHERE observation_id=?",
        (observation["observation_id"],),
    )
    assert list_observations(db, "creator")[0]["metadata"] == {}


@pytest.mark.parametrize("invalid_word", [None, 7, True, {}, []])
def test_visual_association_rejects_non_text_word_without_writing(db, invalid_word):
    record_heard_word(db, "creator", "coq")
    advance_word(db, "creator", "coq", "imitated")
    observation = record_observation(
        db, "creator", "vision", "Un animal", "camera"
    )
    with pytest.raises(ValueError, match="mot"):
        associate_word_with_observation(
            db, "creator", invalid_word, observation["observation_id"],
            "Validation explicite du mot"
        )
    assert db.execute("SELECT COUNT(*) FROM word_visual_associations").fetchone()[0] == 0
