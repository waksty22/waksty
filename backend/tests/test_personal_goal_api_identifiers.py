"""Route-level tests for strict personal learning goal identifiers."""
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


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def goals_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            progress REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE goal_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES goals(id),
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO goals(user_id,title) VALUES('creator','Objectif');
        INSERT INTO goal_steps(goal_id,description) VALUES(1,'Étape');
    """)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1"])
@pytest.mark.parametrize("field", ["goal_id", "step_id"])
def test_goal_step_route_rejects_coerced_ids_without_mutation(
    goals_api_db, bad_id, field
):
    payload = {
        "goal_id": 1,
        "step_id": 1,
        "evidence": "Preuve vérifiable",
        "completed": True,
    }
    payload[field] = bad_id

    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_record_personal_goal_step(
            JsonRequest(payload), auth="creator"
        ))

    assert error.value.status_code == 422
    step = goals_api_db.execute(
        "SELECT status, evidence FROM goal_steps WHERE id=1"
    ).fetchone()
    assert step["status"] == "pending"
    assert step["evidence"] == ""
    goal = goals_api_db.execute(
        "SELECT status, progress FROM goals WHERE id=1"
    ).fetchone()
    assert goal["status"] == "active"
    assert goal["progress"] == 0
