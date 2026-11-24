"""Route-level guardrails for human review of cross-modal candidates."""
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
from learning.sensory import init_sensory_tables, record_observation
from learning.perception_fusion import (
    init_perception_fusion_tables,
    link_temporally_cooccurring_observation,
    list_perception_fusions,
)


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


@pytest.fixture
def fusion_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    init_sensory_tables(db)
    init_perception_fusion_tables(db)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


def create_candidate(db, user_id="creator"):
    audio = record_observation(
        db, user_id, "audio", "J'entends pomme.", "confirmed_transcription"
    )
    record_observation(
        db, user_id, "vision", "Une pomme rouge est visible.", "camera_snapshot"
    )
    candidates = link_temporally_cooccurring_observation(
        db, user_id, audio["observation_id"]
    )
    assert len(candidates) == 1
    return candidates[0]["id"]


def test_review_route_confirms_candidate_for_authenticated_owner(fusion_api_db):
    candidate_id = create_candidate(fusion_api_db)
    result = asyncio.run(server.api_review_perception_fusion(
        candidate_id,
        JsonRequest({
            "decision": "confirm",
            "evidence": "Le Créateur confirme que la pomme entendue est l'objet montré.",
        }),
        auth="creator",
    ))

    assert result["ok"] is True
    assert result["review"]["status"] == "confirmed"
    assert result["review"]["world_knowledge_promoted"] is False
    assert list_perception_fusions(fusion_api_db, "creator")[0]["status"] == "confirmed"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "confirm",
        7,
    ],
)
def test_review_route_rejects_non_object_json_without_writing(fusion_api_db, payload):
    candidate_id = create_candidate(fusion_api_db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_review_perception_fusion(
            candidate_id, JsonRequest(payload), auth="creator"
        ))
    assert error.value.status_code == 422
    assert list_perception_fusions(fusion_api_db, "creator")[0]["status"] == "candidate"


def test_review_route_rejects_malformed_json_without_writing(fusion_api_db):
    candidate_id = create_candidate(fusion_api_db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_review_perception_fusion(
            candidate_id, JsonRequest(ValueError("invalid JSON")), auth="creator"
        ))
    assert error.value.status_code == 422
    assert list_perception_fusions(fusion_api_db, "creator")[0]["status"] == "candidate"


def test_review_route_prevents_cross_user_candidate_access(fusion_api_db):
    candidate_id = create_candidate(fusion_api_db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_review_perception_fusion(
            candidate_id,
            JsonRequest({
                "decision": "confirm",
                "evidence": "Cette tentative vient d'un autre utilisateur.",
            }),
            auth="another-user",
        ))
    assert error.value.status_code == 422
    assert list_perception_fusions(fusion_api_db, "creator")[0]["status"] == "candidate"
    assert list_perception_fusions(fusion_api_db, "another-user") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "maybe", "evidence": "Une preuve présente."},
        {"decision": "confirm", "evidence": ""},
        {"decision": "reject", "evidence": "   "},
        {"decision": "confirm", "evidence": "x" * 1001},
        {"decision": "confirm", "evidence": 42},
    ],
)
def test_review_route_rejects_invalid_decision_or_evidence(fusion_api_db, payload):
    candidate_id = create_candidate(fusion_api_db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_review_perception_fusion(
            candidate_id, JsonRequest(payload), auth="creator"
        ))
    assert error.value.status_code == 422
    assert list_perception_fusions(fusion_api_db, "creator")[0]["status"] == "candidate"
