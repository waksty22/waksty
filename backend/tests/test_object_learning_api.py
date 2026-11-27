"""Tests for the Creator-approved object-property correction API."""
import asyncio
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from learning.language import init_language_tables, record_heard_word, advance_word
from learning.sensory import init_sensory_tables, record_observation, associate_word_with_observation
from learning.object_learning import init_object_learning_tables, teach_object_property
from world.world_model import init_world_tables, upsert_world_entity


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def object_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE conversations (
            id INTEGER PRIMARY KEY, user_id TEXT, role TEXT,
            content TEXT, created_at TEXT
        )"""
    )
    init_language_tables(db)
    init_world_tables(db)
    init_sensory_tables(db)
    init_object_learning_tables(db)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    record_heard_word(db, "creator", "pomme")
    advance_word(db, "creator", "pomme", "imitated")
    advance_word(db, "creator", "pomme", "recognized")
    observation = record_observation(
        db, "creator", "vision", "image de pomme", "camera_frame", 0.9
    )
    associate_word_with_observation(
        db, "creator", "pomme", observation["observation_id"],
        "Association visuelle validée",
    )
    upsert_world_entity(
        db, "creator", "object:pomme", "object",
        {"label": "pomme"}, source_type="taught", confidence=0.65,
    )
    teach_object_property(
        db, "creator", "pomme", "couleur", "rouge",
        evidence="Première leçon du Créateur.",
    )
    yield db
    db.close()


def test_object_correction_api_requires_explicit_creator_approval(object_api_db):
    payload = {
        "word": "pomme",
        "property": "couleur",
        "previous_value": "rouge",
        "value": "jaune",
        "evidence": "Correction explicite du Créateur après vérification.",
        "supervisor_approved": False,
    }
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_correct_object_property(
            JsonRequest(payload), auth="creator"
        ))
    assert error.value.status_code == 403
    assert object_api_db.execute(
        "SELECT property_value FROM object_properties"
    ).fetchone()[0] == "rouge"
    assert object_api_db.execute(
        "SELECT COUNT(*) FROM object_property_history"
    ).fetchone()[0] == 0


def test_object_correction_api_updates_current_value_and_preserves_history(object_api_db):
    payload = {
        "word": "pomme",
        "property": "couleur",
        "previous_value": "rouge",
        "value": "jaune",
        "evidence": "Correction explicite du Créateur après vérification.",
        "supervisor_approved": True,
    }
    result = asyncio.run(server.api_correct_object_property(
        JsonRequest(payload), auth="creator"
    ))
    assert result["ok"] is True
    assert result["history_preserved"] is True
    assert object_api_db.execute(
        "SELECT property_value, source_type FROM object_properties"
    ).fetchone()["property_value"] == "jaune"
    assert object_api_db.execute(
        "SELECT previous_value, corrected_value FROM object_property_history"
    ).fetchone()["previous_value"] == "rouge"
