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


def test_explicit_correction_api_requires_creator_approval_and_preserves_history(
    language_api_db,
):
    from learning.language import record_explicit_word_teaching

    record_explicit_word_teaching(
        language_api_db, "creator",
        "Le mot coq signifie un oiseau domestique.",
    )

    def correction(approved):
        return server.VocabularyCorrectionRequest(
            word="coq",
            meaning="Un oiseau mâle de la famille des gallinacés.",
            evidence="Le créateur corrige explicitement la définition après vérification.",
            supervisor_approved=approved,
        )

    async def run():
        with pytest.raises(HTTPException) as denied:
            await server.api_correct_vocabulary(
                correction(False), auth="creator"
            )
        assert denied.value.status_code == 403
        result = await server.api_correct_vocabulary(
            correction(True), auth="creator"
        )
        assert result["ok"] is True
        assert result["word"]["history_preserved"] is True

    asyncio.run(run())
    current = language_api_db.execute(
        "SELECT meaning, state FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()
    history = language_api_db.execute(
        "SELECT previous_meaning, corrected_meaning FROM personal_vocabulary_history WHERE user_id='creator' AND word='coq'"
    ).fetchone()
    assert current["meaning"] == "Un oiseau mâle de la famille des gallinacés."
    assert current["state"] == "heard"
    assert history["previous_meaning"] == "un oiseau domestique"
    assert history["corrected_meaning"] == current["meaning"]


def test_non_creator_cannot_correct_vocabulary_api_even_with_approval(language_api_db):
    from learning.language import record_explicit_word_teaching

    record_explicit_word_teaching(
        language_api_db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    payload = server.VocabularyCorrectionRequest(
        word="coq",
        meaning="Un oiseau mâle.",
        evidence="Correction explicite et vérifiée par le Créateur.",
        supervisor_approved=True,
    )
    async def run():
        with pytest.raises(HTTPException) as denied:
            await server.api_correct_vocabulary(payload, auth="other")
        assert denied.value.status_code == 403
    asyncio.run(run())
    assert language_api_db.execute(
        "SELECT meaning FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()[0] == "un oiseau domestique"
    assert language_api_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary_history"
    ).fetchone()[0] == 0


def test_chat_can_correct_vocabulary_from_explicit_creator_statement(language_api_db):
    from learning.language import record_explicit_word_teaching

    record_explicit_word_teaching(
        language_api_db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    result = server.execute_tool(
        "correct_word_definition",
        {"word": "coq", "meaning": "un oiseau mâle"},
        "creator",
        user_source_text="Non, le coq signifie un oiseau mâle.",
    )
    assert result["corrected"] is True
    assert result["history_preserved"] is True
    assert language_api_db.execute(
        "SELECT meaning FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()[0] == "un oiseau mâle"
    assert language_api_db.execute(
        "SELECT previous_meaning, corrected_meaning FROM personal_vocabulary_history"
    ).fetchone()[:] == ("un oiseau domestique", "un oiseau mâle")


@pytest.mark.parametrize(
    ("user_id", "message"),
    [
        ("other", "Non, le coq signifie un oiseau mâle."),
        ("creator", "Est-ce que le coq signifie un oiseau mâle ?"),
        ("creator", "Non, le coq signifie peut-être un oiseau mâle."),
        ("creator", "Ne corrige pas le coq en oiseau mâle."),
        ("creator", "Non, la coque signifie un oiseau mâle."),
    ],
)
def test_chat_rejects_ambiguous_or_non_creator_vocabulary_corrections(
    language_api_db, user_id, message
):
    from learning.language import record_explicit_word_teaching

    record_explicit_word_teaching(
        language_api_db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    result = server.execute_tool(
        "correct_word_definition",
        {"word": "coq", "meaning": "un oiseau mâle"},
        user_id,
        user_source_text=message,
    )
    assert result["corrected"] is False
    assert language_api_db.execute(
        "SELECT meaning FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()[0] == "un oiseau domestique"
    assert language_api_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary_history"
    ).fetchone()[0] == 0


def test_non_creator_cannot_promote_vocabulary_even_with_approval(language_api_db):
    async def run():
        await server.api_teach_vocabulary(
            payload("pomme", "heard"), auth="other"
        )
        with pytest.raises(HTTPException) as denied:
            await server.api_teach_vocabulary(
                payload(
                    "pomme", "imitated",
                    evidence="Le mot a été répété correctement plusieurs fois.",
                    supervisor_approved=True,
                ),
                auth="other",
            )
        assert denied.value.status_code == 403

    asyncio.run(run())
    row = language_api_db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id='other' AND word='pomme'"
    ).fetchone()
    assert row["state"] == "heard"
