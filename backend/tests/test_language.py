import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.language import (
    advance_word,
    gate_spoken_text,
    get_repeatable_words,
    get_usable_words,
    init_language_tables,
    record_heard_word,
    record_heard_text,
    text_uses_only_allowed_words,
)


@pytest.fixture
def language_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_language_tables(db)
    yield db
    db.close()


def test_new_word_is_only_repeatable_after_it_is_heard(language_db):
    record_heard_word(language_db, "creator", "montre", "Mot prononcé par le créateur")

    assert get_repeatable_words(language_db, "creator") == {"montre"}
    assert get_usable_words(language_db, "creator") == set()
    assert gate_spoken_text("montre coq", get_repeatable_words(language_db, "creator")) == "montre"


def test_word_requires_stepwise_learning(language_db):
    record_heard_word(language_db, "creator", "coq")

    with pytest.raises(ValueError):
        advance_word(language_db, "creator", "coq", "recognized")

    advance_word(language_db, "creator", "coq", "imitated")
    advance_word(language_db, "creator", "coq", "recognized")
    advance_word(language_db, "creator", "coq", "understood", meaning="Un animal qui chante")
    advance_word(language_db, "creator", "coq", "usable", meaning="Un animal qui chante")

    assert get_usable_words(language_db, "creator") == {"coq"}


def test_unknown_words_are_never_added_to_output(language_db):
    record_heard_word(language_db, "creator", "pomme")
    allowed = get_repeatable_words(language_db, "creator")

    assert gate_spoken_text("Je vois une pomme rouge", allowed) == "pomme"
    assert gate_spoken_text("Bonjour, comment vas-tu ?", set()) == ""
    assert gate_spoken_text(
        "je vois une montre", {"je", "vois", "une", "montre"}, max_words=1
    ) == "je"


def test_live_transcript_gate_blocks_unknown_words():
    allowed = {"bonjour", "chappie", "oui"}
    assert text_uses_only_allowed_words("Bonjour Chappie !", allowed)
    assert not text_uses_only_allowed_words("Bonjour ami !", allowed)
    assert not text_uses_only_allowed_words("", allowed)



def test_written_chat_records_words_as_heard_without_promoting_comprehension(language_db):
    heard = record_heard_text(
        language_db,
        "creator",
        "Bonjour Chappie, regarde la montre.",
        evidence="Message écrit reçu par le chat classique",
    )

    assert {item["word"] for item in heard} == {
        "bonjour", "chappie", "regarde", "la", "montre"
    }
    assert get_repeatable_words(language_db, "creator") == {
        "bonjour", "chappie", "regarde", "la", "montre"
    }
    assert get_usable_words(language_db, "creator") == set()


def test_newborn_chat_falls_back_to_one_word_heard_in_current_message(language_db):
    message = "Bonjour Chappie"
    record_heard_text(language_db, "creator", message, evidence="Chat écrit")

    allowed = get_repeatable_words(language_db, "creator")
    generated_reply = gate_spoken_text(
        "Je suis heureux de te parler.",
        allowed,
        max_words=1,
    )
    imitation_fallback = gate_spoken_text(
        message,
        allowed,
        max_words=1,
    )

    assert generated_reply == ""
    assert gate_spoken_text("...", allowed, max_words=1) == ""
    assert imitation_fallback == "Bonjour"
    assert text_uses_only_allowed_words(imitation_fallback, allowed)


def test_chat_and_live_lexical_exposure_share_persistent_user_vocabulary(tmp_path):
    """Confirmed text from both modalities survives a fresh DB connection."""
    database_path = tmp_path / "shared-vocabulary.sqlite3"

    def connect():
        db = sqlite3.connect(database_path)
        db.row_factory = sqlite3.Row
        init_language_tables(db)
        return db

    first = connect()
    try:
        record_heard_text(
            first,
            "creator",
            "La chaussure est ici.",
            evidence="Message écrit reçu par le chat classique",
        )
        record_heard_text(
            first,
            "creator",
            "La chaussure est là, voici le vélo.",
            evidence="Transcription confirmée par Gemini Live",
        )
        first.commit()
    finally:
        first.close()

    reopened = connect()
    try:
        from learning.language import list_vocabulary

        vocabulary = {
            item["word"]: item for item in list_vocabulary(reopened, "creator")
        }
        assert {"la", "chaussure", "est", "ici", "là", "voici", "le", "vélo"} <= set(vocabulary)
        assert vocabulary["chaussure"]["exposure_count"] == 2
        assert vocabulary["chaussure"]["state"] == "heard"
        assert get_repeatable_words(reopened, "creator") >= {"chaussure", "vélo"}
        assert get_usable_words(reopened, "creator") == set()
        assert get_repeatable_words(reopened, "another-user") == set()
    finally:
        reopened.close()


@pytest.mark.parametrize("invalid_text", [None, 7, True, {}, []])
def test_heard_text_rejects_non_text_input_without_writing(language_db, invalid_text):
    with pytest.raises(ValueError, match="texte|chaîne"):
        record_heard_text(language_db, "creator", invalid_text)
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_text", [None, 7, True, {}, []])
def test_explicit_teaching_rejects_non_text_input_without_writing(language_db, invalid_text):
    from learning.language import record_explicit_word_teaching

    with pytest.raises(ValueError, match="texte|chaîne"):
        record_explicit_word_teaching(language_db, "creator", invalid_text)
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_evidence", [None, 7, True, {}, []])
def test_heard_word_rejects_non_text_evidence_without_writing(language_db, invalid_evidence):
    with pytest.raises(ValueError, match="preuve|texte"):
        record_heard_word(
            language_db, "creator", "pomme", evidence=invalid_evidence
        )
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_evidence", [None, 7, True, {}, []])
def test_heard_text_rejects_non_text_evidence_without_writing(language_db, invalid_evidence):
    with pytest.raises(ValueError, match="preuve|texte"):
        record_heard_text(
            language_db, "creator", "Bonjour Chappie", evidence=invalid_evidence
        )
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_value", [None, 7, True, {}, []])
@pytest.mark.parametrize("field", ["meaning", "evidence"])
def test_word_progression_rejects_non_text_metadata_without_updating(
    language_db, invalid_value, field
):
    record_heard_word(language_db, "creator", "pomme")
    kwargs = {field: invalid_value}
    with pytest.raises(ValueError, match="texte"):
        advance_word(
            language_db, "creator", "pomme", "imitated", **kwargs
        )
    row = language_db.execute(
        "SELECT state, meaning FROM personal_vocabulary WHERE user_id=? AND word=?",
        ("creator", "pomme"),
    ).fetchone()
    assert row["state"] == "heard"
    assert row["meaning"] == ""


@pytest.mark.parametrize("invalid_text", [None, 7, True, {}, []])
def test_vocabulary_text_gate_fails_closed_for_non_text_input(invalid_text):
    assert not text_uses_only_allowed_words(invalid_text, {"bonjour"})
    assert gate_spoken_text(invalid_text, {"bonjour"}) == ""


@pytest.mark.parametrize("invalid_limit", [None, 0, -1, True, 1.5, "2"])
def test_heard_text_rejects_invalid_token_limits_without_writing(language_db, invalid_limit):
    with pytest.raises(ValueError, match="limite|entier"):
        record_heard_text(
            language_db, "creator", "Bonjour Chappie", max_tokens=invalid_limit
        )
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0
