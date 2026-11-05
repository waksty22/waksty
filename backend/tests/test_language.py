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
