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
