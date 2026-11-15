import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import init_language_tables, record_heard_word, advance_word
from learning.object_learning import (
    init_object_learning_tables,
    teach_object_property,
    list_known_objects,
    compare_known_objects,
    record_object_experience,
)
from learning.sensory import (
    init_sensory_tables, record_observation, associate_word_with_observation,
)
from world.world_model import init_world_tables, upsert_world_entity


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_language_tables(connection)
    init_world_tables(connection)
    init_sensory_tables(connection)
    init_object_learning_tables(connection)
    yield connection
    connection.close()


def validate_visual_association(db, word):
    observation = record_observation(
        db, "creator", "vision", f"image de {word}", "camera_frame", 0.9
    )
    associate_word_with_observation(
        db, "creator", word, observation["observation_id"],
        "Association visuelle explicitement validée",
    )


def add_recognized_object(db, word):
    record_heard_word(db, "creator", word)
    advance_word(db, "creator", word, "imitated")
    advance_word(db, "creator", word, "recognized")
    validate_visual_association(db, word)
    upsert_world_entity(
        db, "creator", "object:" + word, "object",
        {"label": word}, source_type="taught", confidence=0.65,
    )


def test_object_properties_require_recognized_word_and_visual_entity(db):
    record_heard_word(db, "creator", "pomme")
    with pytest.raises(ValueError):
        teach_object_property(db, "creator", "pomme", "couleur", "rouge")

    advance_word(db, "creator", "pomme", "imitated")
    with pytest.raises(ValueError):
        teach_object_property(db, "creator", "pomme", "couleur", "rouge")

    advance_word(db, "creator", "pomme", "recognized")
    upsert_world_entity(
        db, "creator", "object:pomme", "object",
        {"label": "pomme"}, source_type="taught", confidence=0.65,
    )
    # A world entity alone must not bypass explicit sensory validation.
    with pytest.raises(ValueError, match="valide son association visuelle"):
        teach_object_property(db, "creator", "pomme", "couleur", "rouge")

    validate_visual_association(db, "pomme")
    learned = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Le créateur lui montre une pomme rouge.",
    )
    assert learned["property_value"] == "rouge"
    assert learned["source_type"] == "taught"


def test_comparison_never_treats_unknown_as_opposite(db):
    add_recognized_object(db, "pomme")
    add_recognized_object(db, "banane")
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")
    teach_object_property(db, "creator", "pomme", "forme", "ronde")
    teach_object_property(db, "creator", "banane", "forme", "courbée")

    result = compare_known_objects(db, "creator", "pomme", "banane")
    assert result["shared_properties"] == {}
    assert result["differences"]["forme"]["pomme"] == ["ronde"]
    assert result["differences"]["forme"]["banane"] == ["courbée"]
    assert result["differences"]["couleur"]["banane"] == []
    assert "inconnue" in result["warning"]


def test_supervised_experience_is_not_promoted_to_general_property(db):
    add_recognized_object(db, "balle")
    experience = record_object_experience(
        db, "creator", "balle", "pousser doucement",
        "la balle roule sur le sol",
    )
    assert experience["promoted_to_property"] is False
    objects = list_known_objects(db, "creator")
    assert objects[0]["experiences"][0]["outcome"] == "la balle roule sur le sol"
    assert objects[0]["properties"] == []


@pytest.mark.parametrize(
    "confidence",
    [None, "not-a-number", float("inf"), float("nan")],
)
def test_object_experience_rejects_invalid_confidence_without_writing(db, confidence):
    add_recognized_object(db, "balle")
    with pytest.raises(ValueError, match="Confiance|confiance"):
        record_object_experience(
            db, "creator", "balle", "lancer", "la balle roule",
            confidence=confidence,
        )
    count = db.execute(
        "SELECT COUNT(*) FROM object_experiences"
    ).fetchone()[0]
    assert count == 0


def test_users_cannot_read_or_teach_another_users_object(db):
    add_recognized_object(db, "montre")
    with pytest.raises(ValueError):
        teach_object_property(db, "other", "montre", "matiere", "metal")
