"""API-level guardrails for supervised newborn vocabulary progression."""
import asyncio
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from learning.language import init_language_tables


@pytest.fixture
def language_api_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_language_tables(db)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


def payload(word, state, **extra):
    return server.VocabularyTeachRequest(
        word=word, state=state, **extra
    )


def test_vocabulary_api_requires_explicit_supervisor_approval(language_api_db):
    async def run():
        await server.api_teach_vocabulary(
            payload("coq", "heard"), auth="creator"
        )
        with pytest.raises(HTTPException) as exc:
            await server.api_teach_vocabulary(
                payload("coq", "imitated", evidence="Imitation répétée observée"),
                auth="creator",
            )
        assert exc.value.status_code == 403

    asyncio.run(run())
    row = language_api_db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()
    assert row["state"] == "heard"


def test_vocabulary_api_requires_concrete_evidence_and_meaning(language_api_db):
    async def run():
        await server.api_teach_vocabulary(
            payload("coq", "heard"), auth="creator"
        )
        approved = {"supervisor_approved": True}
        with pytest.raises(HTTPException) as short_evidence:
            await server.api_teach_vocabulary(
                payload("coq", "imitated", evidence="Oui", **approved),
                auth="creator",
            )
        assert short_evidence.value.status_code == 422

        await server.api_teach_vocabulary(
            payload(
                "coq", "imitated",
                evidence="Chappie a répété correctement le mot à voix haute.",
                **approved,
            ),
            auth="creator",
        )
        await server.api_teach_vocabulary(
            payload(
                "coq", "recognized",
                evidence="Il a associé le mot à l'image correcte.",
                **approved,
            ),
            auth="creator",
        )
        with pytest.raises(HTTPException) as missing_meaning:
            await server.api_teach_vocabulary(
                payload(
                    "coq", "understood",
                    evidence="Il a expliqué ce que représente le mot.",
                    **approved,
                ),
                auth="creator",
            )
        assert missing_meaning.value.status_code == 422

    asyncio.run(run())
    row = language_api_db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()
    assert row["state"] == "recognized"


def test_vocabulary_api_can_progress_one_supervised_stage_at_a_time(language_api_db):
    async def run():
        await server.api_teach_vocabulary(
            payload("montre", "heard"), auth="creator"
        )
        approval = {"supervisor_approved": True}
        await server.api_teach_vocabulary(
            payload(
                "montre", "imitated",
                evidence="Chappie a répété correctement le mot.",
                **approval,
            ),
            auth="creator",
        )
        await server.api_teach_vocabulary(
            payload(
                "montre", "recognized",
                evidence="Chappie a reconnu la montre sur une image.",
                **approval,
            ),
            auth="creator",
        )
        await server.api_teach_vocabulary(
            payload(
                "montre", "understood",
                meaning="Objet porté au poignet qui indique l'heure.",
                evidence="Il a expliqué correctement la fonction de la montre.",
                **approval,
            ),
            auth="creator",
        )
        await server.api_teach_vocabulary(
            payload(
                "montre", "usable",
                meaning="Objet porté au poignet qui indique l'heure.",
                evidence="Il a utilisé le mot dans une phrase adaptée.",
                **approval,
            ),
            auth="creator",
        )

    asyncio.run(run())
    row = language_api_db.execute(
        "SELECT state, meaning FROM personal_vocabulary WHERE user_id='creator' AND word='montre'"
    ).fetchone()
    assert row["state"] == "usable"
    assert row["meaning"]


def test_vocabulary_api_rejects_non_boolean_approval():
    with pytest.raises(ValidationError):
        payload("coq", "imitated", supervisor_approved="true")
