"""End-to-end retrieval of explicitly validated multimodal object learning."""
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
from learning.object_learning import (
    init_object_learning_tables,
    teach_object_property,
    record_object_experience,
    list_known_objects,
)
from world.world_model import init_world_tables, upsert_world_entity


def open_db(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    init_language_tables(db)
    init_sensory_tables(db)
    init_perception_fusion_tables(db)
    init_world_tables(db)
    init_object_learning_tables(db)
    return db


def test_validated_multimodal_object_can_be_recalled_after_restart(tmp_path):
    path = tmp_path / "object-brain.sqlite3"
    db = open_db(path)
    try:
        # Hearing a word creates exposure, not knowledge or object identity.
        record_heard_word(db, "creator", "pomme", "Transcription confirmée")
        advance_word(db, "creator", "pomme", "imitated")

        audio = record_observation(
            db, "creator", "audio", "pomme", "gemini_live_transcript", 0.9
        )
        vision = record_observation(
            db, "creator", "vision", "forme rouge arrondie",
            "camera_frame", 0.55,
        )
        candidates = link_temporally_cooccurring_observation(
            db, "creator", audio["observation_id"]
        )
        assert len(candidates) == 1
        assert candidates[0]["requires_validation"] is True
        assert list_perception_fusions(db, "creator")[0]["status"] == "candidate"

        # No semantic object exists until the creator validates the association.
        assert db.execute(
            "SELECT COUNT(*) FROM word_visual_associations"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM world_entities WHERE user_id='creator'"
        ).fetchone()[0] == 0

        link = associate_word_with_observation(
            db, "creator", "pomme", vision["observation_id"],
            "Validation explicite du Créateur",
        )
        assert link["association_saved"] is True
        assert link["vocabulary_state"] == "recognized"

        # The world entity is created only after the validated word-image link.
        upsert_world_entity(
            db, "creator", "object:pomme", "object",
            {"label": "pomme", "visual_observation_id": vision["observation_id"]},
            source_type="confirmed", confidence=0.95,
        )
        teach_object_property(
            db, "creator", "pomme", "couleur", "rouge",
            evidence="Couleur confirmée par le Créateur",
            source_type="confirmed", confidence=0.95,
        )
        experience = record_object_experience(
            db, "creator", "pomme", "être tenue",
            "l'objet reste dans la main",
            evidence="Observation de manipulation",
            source_type="observed", confidence=0.7,
        )
        assert experience["promoted_to_property"] is False
        db.commit()
    finally:
        db.close()

    # Restart all learning modules against the same persistent database.
    reopened = open_db(path)
    try:
        objects = list_known_objects(reopened, "creator")
        assert len(objects) == 1
        apple = objects[0]
        assert apple["word"] == "pomme"
        assert apple["vocabulary_state"] == "recognized"
        assert apple["properties"] == [{
            "property_key": "couleur",
            "property_value": "rouge",
            "source_type": "confirmed",
            "confidence": 0.95,
            "evidence": "Couleur confirmée par le Créateur",
        }]
        assert apple["experiences"][0]["action"] == "être tenue"
        assert apple["experiences"][0]["outcome"] == "l'objet reste dans la main"

        # Both the semantic link and the candidate provenance survive restart.
        assert reopened.execute(
            "SELECT COUNT(*) FROM word_visual_associations WHERE user_id='creator'"
        ).fetchone()[0] == 1
        fusion = list_perception_fusions(reopened, "creator")
        assert fusion[0]["status"] == "candidate"
        assert fusion[0]["evidence"]["rule"] == "temporal_cooccurrence_only"

        # The other user cannot retrieve this object or its learned properties.
        assert list_known_objects(reopened, "another-user") == []
        assert reopened.execute(
            "SELECT COUNT(*) FROM word_visual_associations WHERE user_id='another-user'"
        ).fetchone()[0] == 0
    finally:
        reopened.close()



def test_production_routes_wire_validation_world_model_and_recall():
    server_source = (Path(__file__).resolve().parents[1] / "server.py").read_text(
        encoding="utf-8"
    )
    associate_start = server_source.index("@app.post(\"/api/vision/associate\")")
    associate_end = server_source.index("@app.get(\"/api/learning/objects\")", associate_start)
    associate_route = server_source[associate_start:associate_end]
    assert "associate_word_with_observation(" in associate_route
    assert 'data.get("evidence", "")' in associate_route
    assert 'data.get("word", "")' in associate_route
    assert 'data.get("observation_id", "")' in associate_route
    assert 'str(data.get("word", ""))' not in associate_route
    assert 'str(data.get("observation_id", ""))' not in associate_route
    assert 'str(data.get("evidence", ""))' not in associate_route
    assert "Association validée par le créateur" not in associate_route
    assert "upsert_world_entity(" in associate_route
    assert "add_world_relation(" in associate_route
    assert "db.commit()" in associate_route

    recall_start = server_source.index("@app.get(\"/api/learning/objects\")")
    recall_end = server_source.index("@app.post(\"/api/learning/object-property\")", recall_start)
    recall_route = server_source[recall_start:recall_end]
    assert "list_known_objects(db, user_id)" in recall_route

    vision_start = server_source.index("@app.post(\"/api/vision/analyze\")")
    vision_end = server_source.index("@app.get(\"/api/senses/observations\")", vision_start)
    vision_route = server_source[vision_start:vision_end]
    assert '"is_learned_fact": False' in vision_route
    assert "link_temporally_cooccurring_observation(" in vision_route


def test_object_properties_are_blocked_before_visual_validation(tmp_path):
    db = open_db(tmp_path / "gated-object.sqlite3")
    try:
        record_heard_word(db, "creator", "vélo", "Transcription confirmée")
        advance_word(db, "creator", "vélo", "imitated")
        advance_word(db, "creator", "vélo", "recognized")
        # Even an imitated word is not yet an object Chappie may describe.
        with pytest.raises(ValueError, match="valide son association visuelle"):
            teach_object_property(
                db, "creator", "vélo", "couleur", "bleu",
                evidence="Observation non validée",
            )
        assert list_known_objects(db, "creator") == []
    finally:
        db.close()


def test_object_properties_cannot_cross_user_boundaries(tmp_path):
    db = open_db(tmp_path / "isolated-object.sqlite3")
    try:
        record_heard_word(db, "creator", "vélo", "Transcription confirmée")
        advance_word(db, "creator", "vélo", "imitated")
        vision = record_observation(
            db, "creator", "vision", "deux roues", "camera_frame", 0.6
        )
        associate_word_with_observation(
            db, "creator", "vélo", vision["observation_id"],
            "Validation explicite",
        )
        upsert_world_entity(
            db, "creator", "object:vélo", "object",
            {"label": "vélo"}, source_type="confirmed", confidence=0.95,
        )
        with pytest.raises(ValueError):
            teach_object_property(
                db, "another-user", "vélo", "couleur", "bleu",
                evidence="Tentative d'accès croisé",
            )
        assert list_known_objects(db, "another-user") == []
    finally:
        db.close()
