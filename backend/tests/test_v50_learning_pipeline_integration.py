"""V50 cross-learning smoke test on one shared local libSQL connection."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import libsql

from storage.libsql_adapter import adapt_libsql_connection
from learning.language import (
    init_language_tables, record_heard_word, advance_word, get_usable_words,
)
from learning.sensory import (
    init_sensory_tables, record_observation, associate_word_with_observation,
)
from learning.object_learning import (
    init_object_learning_tables, teach_object_property, list_known_objects,
)
from learning.supervised_learning import (
    init_supervised_learning_tables, record_demonstration,
    record_practice, validate_imitation, list_imitation_learning,
)
from world.world_model import init_world_tables, upsert_world_entity


def test_language_perception_object_and_imitation_share_libsql_connection():
    native = libsql.connect(database=":memory:")
    db = adapt_libsql_connection(native)
    try:
        init_language_tables(db)
        init_sensory_tables(db)
        init_world_tables(db)
        init_object_learning_tables(db)
        init_supervised_learning_tables(db)

        # Vocabulary advances only through the defined learning stages.
        record_heard_word(db, "owner", "pomme", "Mot entendu dans un exercice")
        advance_word(db, "owner", "pomme", "imitated")
        advance_word(db, "owner", "pomme", "recognized")

        # A sensory observation can be linked to a recognized word.
        observation = record_observation(
            db, "owner", "vision", "Une pomme rouge sur une table.",
            "local_test_image", confidence=0.8,
        )
        association = associate_word_with_observation(
            db, "owner", "pomme", observation["observation_id"]
        )
        assert association["vocabulary_state"] == "recognized"

        # Object facts remain grounded in a recognized word and world entity.
        upsert_world_entity(
            db, "owner", "object:pomme", "object", {"label": "pomme"},
            source_type="taught", confidence=0.8,
        )
        learned = teach_object_property(
            db, "owner", "pomme", "couleur", "rouge",
            evidence="Observation synthétique du test.",
        )
        assert learned["property_value"] == "rouge"
        assert list_known_objects(db, "owner")[0]["properties"][0]["property_value"] == "rouge"

        # Imitation stays observed until practice and supervisor approval.
        demo = record_demonstration(
            db, "owner", "saluer de la main",
            "Démonstration synthétique du test.",
        )
        assert demo["status"] == "observed"
        record_practice(
            db, "owner", demo["id"], "geste reproduit",
            "Séquence de pratique synthétique.", True,
        )
        validated = validate_imitation(
            db, "owner", demo["id"], True,
            "Validation explicite du test.",
        )
        assert validated["status"] == "validated"
        assert list_imitation_learning(db, "owner")["statistics"]["validated"] == 1
        assert get_usable_words(db, "owner") == set()
    finally:
        db.close()
