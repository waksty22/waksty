"""Strict identifier validation for causal-learning API routes."""
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
from learning.causal_learning import (
    init_causal_learning_tables,
    record_observation,
    propose_hypothesis,
)


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def causal_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_causal_learning_tables(db)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


def create_observation(db):
    return record_observation(
        db, "creator", "une balle tombe", "elle touche le sol"
    )


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1"])
def test_hypothesis_route_rejects_coerced_observation_ids_without_writing(
    causal_api_db, bad_id
):
    observation = create_observation(causal_api_db)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_propose_causal_hypothesis(
            JsonRequest({
                "observation_id": bad_id,
                "statement": "La balle tombe",
                "predicted_effect": "Elle atteint le sol",
            }),
            auth="creator",
        ))
    assert error.value.status_code == 422
    assert causal_api_db.execute(
        "SELECT COUNT(*) FROM causal_hypotheses"
    ).fetchone()[0] == 0
    assert causal_api_db.execute(
        "SELECT COUNT(*) FROM causal_observations WHERE id=?",
        (observation["id"],),
    ).fetchone()[0] == 1


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1"])
def test_experiment_route_rejects_coerced_hypothesis_ids_without_writing(
    causal_api_db, bad_id
):
    observation = create_observation(causal_api_db)
    hypothesis = propose_hypothesis(
        causal_api_db, "creator", observation["id"],
        "La balle tombe", "Elle atteint le sol",
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_plan_causal_experiment(
            JsonRequest({
                "hypothesis_id": bad_id,
                "environment": "simulation",
                "procedure": "Lâcher une balle virtuelle",
                "prediction": "Elle touche le sol",
                "supervisor_approved": True,
            }),
            auth="creator",
        ))
    assert error.value.status_code == 422
    assert causal_api_db.execute(
        "SELECT COUNT(*) FROM causal_experiments"
    ).fetchone()[0] == 0
    row = causal_api_db.execute(
        "SELECT status FROM causal_hypotheses WHERE id=?",
        (hypothesis["id"],),
    ).fetchone()
    assert row["status"] == "proposed"
