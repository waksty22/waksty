"""End-to-end tests for supervised visual recognition entering the shared brain."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(BACKEND))

import server
from cognition.shared_brain import get_shared_brain_snapshot
from learning.language import advance_word, record_heard_word
from learning.live_visual_observation import build_live_visual_analysis_observation
from learning.sensory import record_observation


class JsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def isolated_visual_learning_db(monkeypatch, tmp_path):
    database_path = tmp_path / "visual-association-shared-brain.sqlite3"
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    server.init_db()
    yield
    # The fixture owns only its temporary SQLite file; production Turso is untouched.


def prepare_imitated_word_and_live_visual_observation(user_id="creator"):
    with server.db_connection() as db:
        record_heard_word(
            db, user_id, "coq", "Mot prononcé par le créateur pendant l'enseignement."
        )
        advance_word(
            db, user_id, "coq", "imitated",
            evidence="Chappie a tenté de répéter le mot coq.",
        )
        visual = build_live_visual_analysis_observation(
            "Un oiseau à plumes est visible dans le cadre.",
            "gemini-3.1-flash-live-preview",
            "Que vois-tu ?",
            "staging-live-session",
            7,
            "image/jpeg",
        )
        assert visual is not None
        observation = record_observation(
            db, user_id, visual["modality"], visual["content"], visual["source"],
            confidence=visual["confidence"], metadata=visual["metadata"],
        )
        db.commit()
    return observation["observation_id"]


def test_supervised_live_visual_association_enters_shared_brain_without_overlearning(
    isolated_visual_learning_db,
):
    observation_id = prepare_imitated_word_and_live_visual_observation()
    evidence = "Le créateur confirme que l'oiseau visible est bien un coq."

    result = asyncio.run(server.api_associate_visual_word(
        JsonRequest({
            "word": "coq",
            "observation_id": observation_id,
            "evidence": evidence,
        }),
        auth="creator",
    ))

    assert result["ok"] is True
    assert result["association"]["association_saved"] is True
    assert result["association"]["vocabulary_state"] == "recognized"

    with server.db_connection() as db:
        vocabulary = db.execute(
            "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
            ("creator", "coq"),
        ).fetchone()
        association = db.execute(
            """SELECT evidence FROM word_visual_associations
               WHERE user_id=? AND word=? AND observation_id=?""",
            ("creator", "coq", observation_id),
        ).fetchone()
        snapshot = get_shared_brain_snapshot(db, "creator", limit=20)

    assert vocabulary["state"] == "recognized"
    assert association["evidence"] == evidence
    assert any(
        row["word"] == "coq" and row["observation_id"] == observation_id
        and row["evidence"] == evidence
        for row in snapshot["word_visual_associations"]
    )
    assert any(
        row["entity_id"] == "object:coq" and row["entity_type"] == "object"
        for row in snapshot["world_entities"]
    )
    assert any(
        row["relation_type"] == "associated_with_visual_observation"
        and row["source_type"] == "taught"
        for row in snapshot["world_relations"]
    )
    assert not any(
        row.get("property_key") == "identity"
        for row in snapshot["object_properties"]
    )


def test_live_visual_association_route_rejects_missing_evidence_without_mutation(
    isolated_visual_learning_db,
):
    observation_id = prepare_imitated_word_and_live_visual_observation()
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_associate_visual_word(
            JsonRequest({
                "word": "coq",
                "observation_id": observation_id,
                "evidence": "   ",
            }),
            auth="creator",
        ))

    assert error.value.status_code == 422
    with server.db_connection() as db:
        state = db.execute(
            "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
            ("creator", "coq"),
        ).fetchone()["state"]
        count = db.execute(
            "SELECT COUNT(*) FROM word_visual_associations WHERE user_id=?",
            ("creator",),
        ).fetchone()[0]
    assert state == "imitated"
    assert count == 0
