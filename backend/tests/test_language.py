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
