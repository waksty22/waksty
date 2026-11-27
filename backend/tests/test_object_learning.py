import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import init_language_tables, record_heard_word, advance_word
from memory.autobiographical import init_autobiographical_tables
from learning.object_learning import (
    init_object_learning_tables,
    teach_object_property,
    confirm_object_property,
    correct_object_property,
    list_known_objects,
    compare_known_objects,
    record_object_experience,
)
from learning.sensory import (
    init_sensory_tables, record_observation, associate_word_with_observation,
)
from world.world_model import init_world_tables, upsert_world_entity, add_world_relation
from cognition.shared_brain import get_shared_brain_snapshot


def test_world_context_marks_conflicting_object_properties_for_chat_and_live(db, monkeypatch):
    import json
    import server

    add_recognized_object(db, "pomme")
    teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Première information enseignée.",
    )
    teach_object_property(
        db, "creator", "pomme", "couleur", "verte",
        evidence="Deuxième information enseignée.",
    )
    monkeypatch.setattr(server, "db_connection", lambda: db)

    context = server.build_world_model_context("creator")
    payload = json.loads(context.splitlines()[1])
    colors = [
        item for item in payload["object_properties"]
        if item["object"] == "object:pomme" and item["property"] == "couleur"
    ]

    assert {item["value"] for item in colors} == {"rouge", "verte"}
    assert all(item["conflict"] is True for item in colors)
    assert all(item["conflicting_values"] == ["rouge", "verte"] for item in colors)
    assert "conflit non résolu" in context




@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE conversations (
            id INTEGER PRIMARY KEY, user_id TEXT, role TEXT,
            content TEXT, created_at TEXT
        )"""
    )
    init_autobiographical_tables(connection)
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


def add_recognized_object(db, word, user_id="creator"):
    record_heard_word(db, user_id, word)
    advance_word(db, user_id, word, "imitated")
    advance_word(db, user_id, word, "recognized")
    observation = record_observation(
        db, user_id, "vision", f"image de {word}", "camera_frame", 0.9
    )
    associate_word_with_observation(
        db, user_id, word, observation["observation_id"],
        "Association visuelle explicitement validée",
    )
    upsert_world_entity(
        db, user_id, "object:" + word, "object",
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
    listed = next(item for item in list_known_objects(db, "creator")
                  if item["word"] == "pomme")
    assert listed["property_conflicts"] == {}


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


def test_lower_confidence_object_observation_cannot_replace_stronger_evidence(db):
    add_recognized_object(db, "pomme")
    taught = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Enseignement détaillé du créateur.",
        confidence=0.9, source_type="taught",
    )
    observed = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Observation visuelle moins fiable.",
        confidence=0.2, source_type="observed",
    )

    assert taught["source_type"] == "taught"
    assert observed["source_type"] == "taught"
    assert observed["confidence"] == pytest.approx(0.9)
    assert observed["evidence"] == "Enseignement détaillé du créateur."

    stored = db.execute(
        """SELECT source_type, confidence, evidence FROM object_properties
           WHERE user_id=? AND object_id=? AND property_key=? AND property_value=?""",
        ("creator", "object:pomme", "couleur", "rouge"),
    ).fetchone()
    assert dict(stored) == {
        "source_type": "taught",
        "confidence": pytest.approx(0.9),
        "evidence": "Enseignement détaillé du créateur.",
    }


@pytest.mark.parametrize("confidence", ["0.8", "1", "0", True, None, {}, []])
def test_object_property_rejects_coerced_confidence_without_writing(db, confidence):
    add_recognized_object(db, "pomme")
    with pytest.raises(ValueError, match="Confiance|confiance"):
        teach_object_property(
            db, "creator", "pomme", "couleur", "rouge",
            confidence=confidence,
        )
    assert db.execute("SELECT COUNT(*) FROM object_properties").fetchone()[0] == 0


@pytest.mark.parametrize("confidence", ["0.8", "1", "0", True, None, {}, []])
def test_object_experience_rejects_coerced_confidence_without_writing(db, confidence):
    add_recognized_object(db, "balle")
    with pytest.raises(ValueError, match="Confiance|confiance"):
        record_object_experience(
            db, "creator", "balle", "lancer", "la balle roule",
            confidence=confidence,
        )
    assert db.execute("SELECT COUNT(*) FROM object_experiences").fetchone()[0] == 0


def test_owner_can_confirm_only_an_existing_object_property(db):
    add_recognized_object(db, "pomme")
    taught = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Le Créateur enseigne que la pomme est rouge.",
        confidence=0.75,
    )
    assert taught["source_type"] == "taught"

    confirmed = confirm_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Vérification explicite du Créateur.",
    )
    assert confirmed["source_type"] == "confirmed"
    assert confirmed["confidence"] == 1.0
    assert confirmed["evidence"] == "Vérification explicite du Créateur."

    later_teaching = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Répétition ultérieure.", confidence=1.0,
    )
    assert later_teaching["source_type"] == "confirmed"
    assert later_teaching["evidence"] == "Vérification explicite du Créateur."


def test_creator_correction_preserves_old_object_property_evidence(db):
    add_recognized_object(db, "pomme")
    original = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Première leçon du Créateur.", confidence=0.8,
    )

    corrected = correct_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        "jaune", "Correction explicite du Créateur après vérification.",
    )

    assert corrected["previous_value"] == "rouge"
    assert corrected["property_value"] == "jaune"
    assert corrected["source_type"] == "confirmed"
    assert corrected["confidence"] == 1.0
    assert corrected["history_preserved"] is True

    current = db.execute(
        """SELECT property_value, source_type, confidence, evidence
           FROM object_properties WHERE id=?""",
        (db.execute("SELECT id FROM object_properties WHERE user_id='creator'").fetchone()[0],),
    ).fetchone()
    assert current["property_value"] == "jaune"
    assert current["source_type"] == "confirmed"
    history = db.execute(
        """SELECT previous_value, corrected_value, previous_source_type,
                  previous_confidence, previous_evidence, correction_evidence
           FROM object_property_history WHERE id=?""",
        (corrected["history_id"],),
    ).fetchone()
    assert dict(history) == {
        "previous_value": "rouge",
        "corrected_value": "jaune",
        "previous_source_type": "taught",
        "previous_confidence": 0.8,
        "previous_evidence": "Première leçon du Créateur.",
        "correction_evidence": "Correction explicite du Créateur après vérification.",
    }


def test_object_property_correction_is_user_scoped_and_requires_existing_value(db):
    add_recognized_object(db, "poire")
    teach_object_property(db, "creator", "poire", "couleur", "rouge")
    # The global world-entity ID belongs to the Creator; another user must
    # not gain access to that user's learned property through shared vocabulary
    # or a visual association of their own.
    record_heard_word(db, "other", "poire")
    advance_word(db, "other", "poire", "imitated")
    advance_word(db, "other", "poire", "recognized")
    observation = record_observation(
        db, "other", "vision", "image de poire", "camera_frame", 0.9
    )
    associate_word_with_observation(
        db, "other", "poire", observation["observation_id"],
        "Association visuelle validée",
    )
    with pytest.raises(ValueError, match="valide son association visuelle"):
        correct_object_property(
            db, "other", "poire", "couleur", "rouge", "jaune", "preuve",
        )
    with pytest.raises(ValueError, match="introuvable"):
        correct_object_property(
            db, "creator", "poire", "couleur", "bleue", "jaune", "preuve",
        )
    assert db.execute("SELECT COUNT(*) FROM object_property_history").fetchone()[0] == 0


def test_object_property_correction_rejects_empty_or_duplicate_values(db):
    add_recognized_object(db, "pomme")
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")
    teach_object_property(db, "creator", "pomme", "couleur", "jaune")
    with pytest.raises(ValueError):
        correct_object_property(
            db, "creator", "pomme", "couleur", "rouge", "rouge", "preuve",
        )
    with pytest.raises(ValueError, match="existe déjà"):
        correct_object_property(
            db, "creator", "pomme", "couleur", "rouge", "jaune", "preuve",
        )
    with pytest.raises(ValueError, match="preuve explicite"):
        correct_object_property(
            db, "creator", "pomme", "couleur", "rouge", "verte", "",
        )
    assert db.execute("SELECT COUNT(*) FROM object_property_history").fetchone()[0] == 0


def test_owner_cannot_confirm_missing_property_or_without_evidence(db):
    add_recognized_object(db, "pomme")
    with pytest.raises(ValueError, match="n'existe pas"):
        confirm_object_property(
            db, "creator", "pomme", "couleur", "rouge",
            evidence="Je confirme.",
        )
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")
    with pytest.raises(ValueError, match="preuve explicite"):
        confirm_object_property(
            db, "creator", "pomme", "couleur", "rouge", evidence="",
        )
    stored = db.execute(
        "SELECT source_type FROM object_properties WHERE user_id=?",
        ("creator",),
    ).fetchone()
    assert stored["source_type"] == "taught"


def test_object_property_confirmation_endpoint_requires_authenticated_post():
    import server

    matches = [
        route for route in server.app.routes
        if getattr(route, "path", None) == "/api/learning/object-property/confirm"
    ]
    assert len(matches) == 1
    route = matches[0]
    assert "POST" in route.methods
    assert any(
        dependency.call is server.require_auth
        for dependency in route.dependant.dependencies
    )


def test_object_experience_can_link_only_an_explicit_same_user_episode(db):
    add_recognized_object(db, "balle")
    db.execute(
        """INSERT INTO conversations (id, user_id, role, content, created_at)
           VALUES (1, 'creator', 'user', 'Julien montre une balle', '2026-11-25T10:00:00Z')"""
    )
    db.execute(
        """INSERT INTO autobiographical_events
           (id, user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES (11, 'creator', 1, 'user', 'user_statement',
                   'Julien montre une balle', '2026-11-25T10:00:00Z', 3,
                   '2026-11-25T10:00:00Z')"""
    )
    experience = record_object_experience(
        db, "creator", "balle", "pousser", "la balle roule",
        autobiographical_event_id=11,
    )
    assert experience["autobiographical_event_id"] == 11
    stored = db.execute(
        "SELECT autobiographical_event_id FROM object_experiences WHERE id=?",
        (experience["id"],),
    ).fetchone()
    assert stored["autobiographical_event_id"] == 11


@pytest.mark.parametrize("invalid_id", [True, False, 0, -1, "11", 11.0, {}, []])
def test_object_experience_rejects_invalid_episode_id_without_writing(db, invalid_id):
    add_recognized_object(db, "balle")
    with pytest.raises(ValueError, match="identifiant d'épisode"):
        record_object_experience(
            db, "creator", "balle", "pousser", "la balle roule",
            autobiographical_event_id=invalid_id,
        )
    assert db.execute("SELECT COUNT(*) FROM object_experiences").fetchone()[0] == 0


def test_object_experience_rejects_another_users_episode(db):
    add_recognized_object(db, "balle")
    db.execute(
        """INSERT INTO conversations (id, user_id, role, content, created_at)
           VALUES (2, 'other', 'user', 'Une autre balle', '2026-11-25T10:00:00Z')"""
    )
    db.execute(
        """INSERT INTO autobiographical_events
           (id, user_id, source_conversation_id, actor, event_type, content,
            happened_at, importance, created_at)
           VALUES (12, 'other', 2, 'user', 'user_statement',
                   'Une autre balle', '2026-11-25T10:00:00Z', 3,
                   '2026-11-25T10:00:00Z')"""
    )
    with pytest.raises(ValueError, match="n'existe pas pour cet utilisateur"):
        record_object_experience(
            db, "creator", "balle", "pousser", "la balle roule",
            autobiographical_event_id=12,
        )
    assert db.execute("SELECT COUNT(*) FROM object_experiences").fetchone()[0] == 0



def test_shared_brain_prioritizes_old_object_experience_linked_to_matching_episode(db):
    add_recognized_object(db, "balle")
    db.execute(
        """INSERT INTO conversations(id, user_id, role, content, created_at)
           VALUES (1, 'creator', 'user',
                   'La balle a roulé sous le meuble du salon.',
                   '2026-11-01T10:00:00+00:00')"""
    )
    db.execute(
        """INSERT INTO autobiographical_events
           (id, user_id, source_conversation_id, actor, event_type,
            content, happened_at, importance, created_at)
           VALUES (1, 'creator', 1, 'user', 'user_statement',
                   'La balle a roulé sous le meuble du salon.',
                   '2026-11-01T10:00:00+00:00', 3,
                   '2026-11-01T10:00:00+00:00')"""
    )
    historical = record_object_experience(
        db, "creator", "balle", "pousser", "se déplace",
        evidence="Expérience observée",
        autobiographical_event_id=1,
    )
    for index in range(5):
        record_object_experience(
            db, "creator", "balle", f"action récente {index}",
            f"résultat récent {index}",
            evidence="preuve neutre",
        )
    db.commit()

    snapshot = get_shared_brain_snapshot(
        db, "creator", limit=2, query="meuble salon"
    )

    experiences = snapshot["object_experiences"]
    assert experiences[0]["id"] == historical["id"]
    assert experiences[0]["autobiographical_event_id"] == 1
    assert len(experiences) == 2


def test_known_objects_are_ordered_by_absolute_observation_time(db):
    add_recognized_object(db, "pomme")
    add_recognized_object(db, "banane")
    db.execute("UPDATE world_entities SET last_observed_at=? WHERE id=?",
               ("2026-11-26T09:00:00+02:00", "object:pomme"))
    db.execute("UPDATE world_entities SET last_observed_at=? WHERE id=?",
               ("2026-11-26T08:30:00Z", "object:banane"))
    assert [item["word"] for item in list_known_objects(db, "creator")] == [
        "banane", "pomme"]

def test_multiple_values_for_one_object_property_are_flagged_as_conflicting(db):
    add_recognized_object(db, "pomme")
    first = teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Première information enseignée.",
    )
    second = teach_object_property(
        db, "creator", "pomme", "couleur", "verte",
        evidence="Deuxième information enseignée.",
    )

    listed = next(item for item in list_known_objects(db, "creator")
                  if item["word"] == "pomme")
    colors = [item for item in listed["properties"]
              if item["property_key"] == "couleur"]

    assert {item["property_value"] for item in colors} == {"rouge", "verte"}
    assert listed["property_conflicts"] == {"couleur": ["rouge", "verte"]}
    # The conflict is surfaced, not silently resolved or deleted.
    assert db.execute(
        "SELECT COUNT(*) FROM object_properties WHERE user_id='creator' "
        "AND object_id='object:pomme' AND property_key='couleur'"
    ).fetchone()[0] == 2


def test_object_comparison_surfaces_unresolved_property_conflicts(db):
    add_recognized_object(db, "pomme")
    add_recognized_object(db, "banane")
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")
    teach_object_property(db, "creator", "pomme", "couleur", "verte")
    teach_object_property(db, "creator", "banane", "couleur", "jaune")

    result = compare_known_objects(db, "creator", "pomme", "banane")

    assert result["property_conflicts"] == {
        "pomme": {"couleur": ["rouge", "verte"]},
        "banane": {},
    }
    assert "conflit non résolu" in result["warning"]

def test_repeated_identical_object_property_is_not_a_conflict(db):
    add_recognized_object(db, "pomme")
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")
    teach_object_property(db, "creator", "pomme", "couleur", "rouge")

    listed = next(item for item in list_known_objects(db, "creator")
                  if item["word"] == "pomme")
    assert listed["property_conflicts"] == {}



def test_known_object_list_hides_objects_before_vocabulary_recognition(db):
    word = "toupie"
    record_heard_word(db, "creator", word)
    upsert_world_entity(
        db, "creator", "object:" + word, "object",
        {"label": word}, source_type="observed", confidence=0.6,
    )

    assert list_known_objects(db, "creator") == []

    advance_word(db, "creator", word, "imitated")
    assert list_known_objects(db, "creator") == []

    advance_word(db, "creator", word, "recognized")
    listed = list_known_objects(db, "creator")
    assert len(listed) == 1
    assert listed[0]["word"] == word
    assert listed[0]["vocabulary_state"] == "recognized"
