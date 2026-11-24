"""API-level validation tests for consent-based spatial endpoints."""
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
from world.spatial_memory import init_spatial_tables, start_location_session


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def spatial_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_spatial_tables(db)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


@pytest.mark.parametrize("payload", [None, [], "text", 7, True])
def test_spatial_routes_reject_non_object_json(spatial_api_db, payload):
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_start_location_session(
            JsonRequest(payload), auth="creator"
        ))
    assert error.value.status_code == 422


def test_place_observation_route_does_not_coerce_numeric_description(spatial_api_db):
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_record_place_observation(
            JsonRequest({"description": 123}), auth="creator"
        ))
    assert error.value.status_code == 422
    assert spatial_api_db.execute(
        "SELECT COUNT(*) FROM place_memories"
    ).fetchone()[0] == 0


def test_location_route_does_not_coerce_numeric_coordinate_strings(spatial_api_db):
    session = start_location_session(spatial_api_db, "creator", True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_record_world_location(
            JsonRequest({
                "session_id": session["session_id"],
                "latitude": "48.1",
                "longitude": -2.8
            }), auth="creator"
        ))
    assert error.value.status_code == 422
    assert spatial_api_db.execute(
        "SELECT COUNT(*) FROM spatial_visits"
    ).fetchone()[0] == 0


def test_place_api_does_not_invent_default_confidence(spatial_api_db):
    result = asyncio.run(server.api_record_place_observation(
        JsonRequest({"description": "Un lieu observé sans score"}), auth="creator"
    ))
    assert result["place"]["confidence"] == 0.0
    assert result["place"]["identity_status"] == "unconfirmed"
