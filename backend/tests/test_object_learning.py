import json
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
from world.world_model import init_world_tables, upsert_world_entity, add_world_relation


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


@pytest.mark.parametrize("invalid_evidence", [None, 7, True, {}, []])
def test_object_property_rejects_non_text_evidence_without_writing(db, invalid_evidence):
    add_recognized_object(db, "pomme")
    with pytest.raises(ValueError, match="preuve|texte"):
        teach_object_property(
            db, "creator", "pomme", "couleur", "rouge",
            evidence=invalid_evidence,
        )
    assert db.execute("SELECT COUNT(*) FROM object_properties").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_evidence", [None, 7, True, {}, []])
def test_object_experience_rejects_non_text_evidence_without_writing(db, invalid_evidence):
    add_recognized_object(db, "balle")
    with pytest.raises(ValueError, match="preuve|texte"):
        record_object_experience(
            db, "creator", "balle", "lancer", "la balle roule",
            evidence=invalid_evidence,
        )
    assert db.execute("SELECT COUNT(*) FROM object_experiences").fetchone()[0] == 0


@pytest.mark.parametrize(
    "confidence",
    [None, "not-a-number", float("inf"), float("nan"), True, False],
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


@pytest.mark.parametrize("invalid_source_type", [None, 7, True, {}, [], "unknown"])
def test_object_property_rejects_invalid_provenance_without_writing(db, invalid_source_type):
    add_recognized_object(db, "pomme")
    with pytest.raises(ValueError, match="Provenance"):
        teach_object_property(
            db, "creator", "pomme", "couleur", "rouge",
            source_type=invalid_source_type,
        )
    assert db.execute("SELECT COUNT(*) FROM object_properties").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_source_type", [None, 7, True, {}, [], "unknown"])
def test_object_experience_rejects_invalid_provenance_without_writing(db, invalid_source_type):
    add_recognized_object(db, "balle")
    with pytest.raises(ValueError, match="Provenance"):
        record_object_experience(
            db, "creator", "balle", "lancer", "la balle roule",
            source_type=invalid_source_type,
        )
    assert db.execute("SELECT COUNT(*) FROM object_experiences").fetchone()[0] == 0


@pytest.mark.parametrize("invalid_user_id", [None, 7, True, {}, [], "   "])
def test_object_learning_rejects_invalid_user_identity(db, invalid_user_id):
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        list_known_objects(db, invalid_user_id)
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        teach_object_property(
            db, invalid_user_id, "pomme", "couleur", "rouge"
        )



def test_confirmed_object_property_cannot_be_downgraded_by_later_teaching(db):
    add_recognized_object(db, "pomme")
    confirmed = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Confirmation explicite après vérification.",
        confidence=0.8, source_type="confirmed",
    )
    assert confirmed["source_type"] == "confirmed"

    updated = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Nouvelle répétition de l'enseignement.",
        confidence=0.99, source_type="taught",
    )
    assert updated["source_type"] == "confirmed"
    assert updated["evidence"] == "Confirmation explicite après vérification."
    assert updated["confidence"] == 0.99


def test_comparison_returns_provenance_and_confidence_for_each_value(db):
    add_recognized_object(db, "pomme")
    add_recognized_object(db, "banane")
    teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        confidence=0.9, source_type="taught",
    )
    teach_object_property(
        db, "creator", "banane", "couleur", "jaune",
        confidence=0.6, source_type="observed",
    )

    result = compare_known_objects(db, "creator", "pomme", "banane")
    details = result["property_details"]["couleur"]
    assert details["pomme"][0]["value"] == "rouge"
    assert details["pomme"][0]["source_type"] == "taught"
    assert details["pomme"][0]["confidence"] == 0.9
    assert details["banane"][0]["value"] == "jaune"
    assert details["banane"][0]["source_type"] == "observed"
    assert details["banane"][0]["confidence"] == 0.6


def test_confirmed_world_entity_cannot_be_overwritten_by_higher_confidence_observation(db):
    add_recognized_object(db, "pomme")
    upsert_world_entity(
        db, "creator", "object:pomme", "object",
        {"label": "Pomme vérifiée", "verified_detail": "confirmé"},
        source_type="confirmed", confidence=0.8,
    )

    upsert_world_entity(
        db, "creator", "object:pomme", "object",
        {"label": "Pomme simplement observée"},
        source_type="observed", confidence=0.99,
    )
    row = db.execute(
        "SELECT source_type, properties_json FROM world_entities WHERE id=? AND user_id=?",
        ("object:pomme", "creator"),
    ).fetchone()
    assert row["source_type"] == "confirmed"
    properties = json.loads(row["properties_json"])
    assert properties["label"] == "Pomme vérifiée"
    assert properties["verified_detail"] == "confirmé"


def test_confirmed_world_relation_cannot_be_downgraded_by_higher_confidence_observation(db):
    upsert_world_entity(
        db, "creator", "person:julien", "person",
        {"label": "Julien"}, source_type="taught", confidence=0.7,
    )
    upsert_world_entity(
        db, "creator", "place:home", "place",
        {"label": "Maison"}, source_type="taught", confidence=0.7,
    )

    confirmed = add_world_relation(
        db, "creator", "person:julien", "place:home",
        relation_type="lives_at", source_type="confirmed", confidence=0.7,
    )
    assert confirmed["source_type"] == "confirmed"

    observed = add_world_relation(
        db, "creator", "person:julien", "place:home",
        relation_type="lives_at", source_type="observed", confidence=0.99,
    )
    assert observed["source_type"] == "confirmed"
    assert observed["confidence"] == pytest.approx(0.99)

    row = db.execute(
        """
        SELECT source_type, confidence
        FROM world_relations
        WHERE user_id=? AND subject_id=? AND predicate=? AND object_id=?
        """,
        ("creator", "person:julien", "lives_at", "place:home"),
    ).fetchone()
    assert row["source_type"] == "confirmed"
    assert row["confidence"] == pytest.approx(0.99)


def test_world_relations_are_scoped_to_the_owning_user(db):
    upsert_world_entity(
        db, "creator", "person:julien", "person",
        {"label": "Julien"}, source_type="taught",
    )
    upsert_world_entity(
        db, "creator", "place:home", "place",
        {"label": "Maison"}, source_type="taught",
    )
    with pytest.raises(ValueError, match="n'existe pas"):
        add_world_relation(
            db, "other", "person:julien", "place:home",
            relation_type="lives_at",
        )
