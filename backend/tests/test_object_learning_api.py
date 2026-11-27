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


def test_chat_can_apply_only_an_explicit_owner_object_correction(object_api_db):
    result = server.execute_tool(
        "correct_object_property",
        {
            "word": "pomme",
            "property": "couleur",
            "previous_value": "rouge",
            "value": "jaune",
        },
        "creator",
        user_source_text="Non, la pomme est jaune.",
    )

    assert result["corrected"] is True
    assert result["history_preserved"] is True
    current = object_api_db.execute(
        "SELECT property_value, source_type, confidence FROM object_properties"
    ).fetchone()
    assert tuple(current) == ("jaune", "confirmed", 1.0)
    history = object_api_db.execute(
        "SELECT previous_value, corrected_value, correction_evidence FROM object_property_history"
    ).fetchone()
    assert tuple(history) == ("rouge", "jaune", "Non, la pomme est jaune.")


@pytest.mark.parametrize(
    ("user_id", "message"),
    [
        ("other", "Non, la pomme est jaune."),
        ("creator", "Est-ce que la pomme est jaune ?"),
        ("creator", "Ne corrige pas la pomme en jaune."),
        ("creator", "Je pense que la pomme pourrait être jaune."),
        ("creator", "Non, la pomme est peut-être jaune."),
        ("creator", "Non, la pomme est jaune ?"),
        ("creator", "Non, la pomme est probablement jaune."),
        ("creator", "Non, le pommier est jaune."),
    ],
)
def test_chat_object_correction_rejects_non_owner_or_ambiguous_messages(
    object_api_db, user_id, message
):
    result = server.execute_tool(
        "correct_object_property",
        {
            "word": "pomme",
            "property": "couleur",
            "previous_value": "rouge",
            "value": "jaune",
        },
        user_id,
        user_source_text=message,
    )

    assert result["corrected"] is False
    assert object_api_db.execute(
        "SELECT property_value FROM object_properties"
    ).fetchone()[0] == "rouge"
    assert object_api_db.execute(
        "SELECT COUNT(*) FROM object_property_history"
    ).fetchone()[0] == 0


def test_non_creator_cannot_use_object_correction_endpoint_even_with_approval(object_api_db):
    payload = {
        "word": "pomme",
        "property": "couleur",
        "previous_value": "rouge",
        "value": "jaune",
        "evidence": "Correction explicite.",
        "supervisor_approved": True,
    }
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_correct_object_property(
            JsonRequest(payload), auth="other"
        ))
    assert error.value.status_code == 403
    assert object_api_db.execute(
        "SELECT property_value FROM object_properties"
    ).fetchone()[0] == "rouge"
    assert object_api_db.execute(
        "SELECT COUNT(*) FROM object_property_history"
    ).fetchone()[0] == 0


def test_chat_can_record_a_grounded_object_experience(object_api_db):
    result = server.execute_tool(
        "record_object_experience",
        {
            "word": "pomme",
            "action": "poussé la pomme",
            "outcome": "elle est tombée",
        },
        "creator",
        user_source_text="J'ai poussé la pomme et elle est tombée.",
    )

    assert result["recorded"] is True
    assert result["promoted_to_property"] is False
    assert result["causality_confirmed"] is False
    row = object_api_db.execute(
        """SELECT action, outcome, source_type, confidence, evidence
           FROM object_experiences"""
    ).fetchone()
    assert tuple(row) == (
        "poussé la pomme", "elle est tombée", "taught", 0.9,
        "J'ai poussé la pomme et elle est tombée.",
    )
    assert object_api_db.execute(
        "SELECT COUNT(*) FROM object_properties"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    "message",
    [
        "Est-ce que j'ai poussé la pomme et elle est tombée ?",
        "Je pense avoir poussé la pomme et elle est peut-être tombée.",
        "Je n'ai pas poussé la pomme et elle est tombée.",
        "J'ai peut-être poussé la pomme et elle est tombée.",
    ],
)
def test_chat_rejects_uncertain_or_negated_object_experiences(object_api_db, message):
    result = server.execute_tool(
        "record_object_experience",
        {
            "word": "pomme",
            "action": "poussé la pomme",
            "outcome": "elle est tombée",
        },
        "creator",
        user_source_text=message,
    )

    assert result["recorded"] is False
    assert object_api_db.execute(
        "SELECT COUNT(*) FROM object_experiences"
    ).fetchone()[0] == 0


def test_object_experience_tool_is_declared_for_chat_and_live():
    declarations = server.TOOLS[0]["functionDeclarations"]
    assert any(item["name"] == "record_object_experience" for item in declarations)


def test_non_creator_cannot_confirm_object_property(object_api_db):
    payload = {
        "word": "pomme",
        "property": "couleur",
        "value": "rouge",
        "evidence": "Confirmation explicite.",
    }
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_confirm_object_property(
            JsonRequest(payload), auth="other"
        ))
    assert error.value.status_code == 403
    assert object_api_db.execute(
        "SELECT source_type FROM object_properties"
    ).fetchone()[0] == "taught"
