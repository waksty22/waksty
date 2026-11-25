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


def test_repeated_exposure_does_not_overwrite_learning_evidence(language_db):
    record_heard_word(
        language_db, "creator", "coq", "Première exposition"
    )
    advance_word(
        language_db, "creator", "coq", "imitated",
        evidence="Imitation validée par le créateur",
    )
    advance_word(
        language_db, "creator", "coq", "recognized",
        evidence="Association visuelle validée avec une photo",
    )

    updated = record_heard_word(
        language_db, "creator", "coq", "Nouvelle exposition dans une phrase"
    )

    assert updated["state"] == "recognized"
    assert updated["evidence"] == "Association visuelle validée avec une photo"
    assert updated["exposure_count"] == 2


def test_advancing_word_without_new_evidence_preserves_existing_proof(language_db):
    record_heard_word(
        language_db, "creator", "coq", "Exposition initiale"
    )
    advance_word(
        language_db, "creator", "coq", "imitated",
        evidence="Imitation répétée devant le créateur",
    )
    updated = advance_word(
        language_db, "creator", "coq", "recognized"
    )

    assert updated["state"] == "recognized"
    assert updated["evidence"] == "Imitation répétée devant le créateur"


def test_advancing_word_with_new_evidence_replaces_previous_proof(language_db):
    record_heard_word(
        language_db, "creator", "coq", "Exposition initiale"
    )
    advance_word(
        language_db, "creator", "coq", "imitated",
        evidence="Imitation observée",
    )
    updated = advance_word(
        language_db, "creator", "coq", "recognized",
        evidence="Reconnaissance visuelle validée",
    )

    assert updated["evidence"] == "Reconnaissance visuelle validée"


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


@pytest.mark.parametrize("invalid_state", [None, 7, True, {}, []])
def test_word_progression_rejects_invalid_state_without_updating(language_db, invalid_state):
    record_heard_word(language_db, "creator", "pomme")
    with pytest.raises(ValueError, match="État"):
        advance_word(language_db, "creator", "pomme", invalid_state)
    row = language_db.execute(
        "SELECT state FROM personal_vocabulary WHERE user_id=? AND word=?",
        ("creator", "pomme"),
    ).fetchone()
    assert row["state"] == "heard"


@pytest.mark.parametrize("invalid_limit", [0, -1, True, False, 1.5, "2", {}])
def test_spoken_text_gate_rejects_invalid_word_limits(invalid_limit):
    with pytest.raises(ValueError, match="limite|entier"):
        gate_spoken_text("bonjour", {"bonjour"}, max_words=invalid_limit)


@pytest.mark.parametrize("invalid_user_id", [None, "", "   ", 7, True, {}, []])
def test_vocabulary_write_paths_reject_invalid_user_identity_without_writing(
    language_db, invalid_user_id
):
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        record_heard_word(language_db, invalid_user_id, "pomme")
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        record_heard_text(language_db, invalid_user_id, "bonjour")
    from learning.language import record_explicit_word_teaching
    with pytest.raises(ValueError, match="Identifiant utilisateur"):
        record_explicit_word_teaching(
            language_db, invalid_user_id, "pomme signifie un fruit"
        )
    assert language_db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_user_id", [None, "", "   ", 7, True, {}, []])
def test_vocabulary_read_and_progression_paths_reject_invalid_user_identity(
    language_db, invalid_user_id
):
    from learning.language import list_vocabulary
    for operation in (
        lambda: advance_word(language_db, invalid_user_id, "pomme", "imitated"),
        lambda: list_vocabulary(language_db, invalid_user_id),
        lambda: get_usable_words(language_db, invalid_user_id),
        lambda: get_repeatable_words(language_db, invalid_user_id),
    ):
        with pytest.raises(ValueError, match="Identifiant utilisateur"):
            operation()

def test_ordinary_live_conversation_does_not_become_explicit_word_teaching(language_db):
    from learning.language import record_explicit_word_teaching, list_vocabulary

    taught = record_explicit_word_teaching(
        language_db,
        "creator",
        "Bonjour Chappie. Regarde la montre et le coq dans le jardin.",
        evidence="Enseignement explicite via Gemini Live",
    )

    assert taught == []
    assert list_vocabulary(language_db, "creator") == []


def test_heard_word_exposure_counter_does_not_overflow_sqlite_integer(language_db):
    from learning.language import record_heard_word

    language_db.execute(
        "INSERT INTO personal_vocabulary "
        "(user_id, word, state, exposure_count, evidence, created_at, updated_at) "
        "VALUES (?, ?, 'heard', ?, ?, ?, ?)",
        ("creator", "coq", 9223372036854775807, "test", "now", "now"),
    )

    recorded = record_heard_word(language_db, "creator", "coq")

    assert recorded["exposure_count"] == 9223372036854775807
    assert type(recorded["exposure_count"]) is int


def test_explicit_definition_does_not_double_count_same_message_exposure(language_db):
    from learning.language import record_explicit_word_teaching

    message = "Le mot coq signifie un oiseau domestique qui chante."
    record_heard_text(language_db, "creator", message, evidence="Message écrit")
    taught = record_explicit_word_teaching(
        language_db, "creator", message, evidence="Enseignement explicite"
    )

    assert [item["word"] for item in taught] == ["coq"]
    row = language_db.execute(
        "SELECT exposure_count, meaning, state FROM personal_vocabulary "
        "WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    assert row["exposure_count"] == 1
    assert row["meaning"] == "un oiseau domestique qui chante"
    assert row["state"] == "heard"


def test_explicit_live_definition_is_stored_as_heard_not_understood(language_db):
    from learning.language import record_explicit_word_teaching, list_vocabulary

    taught = record_explicit_word_teaching(
        language_db,
        "creator",
        "Le mot coq signifie un oiseau domestique qui chante.",
        evidence="Enseignement explicite via Gemini Live",
    )

    assert len(taught) == 1
    assert taught[0]["word"] == "coq"
    assert taught[0]["meaning"] == "un oiseau domestique qui chante"
    assert taught[0]["state"] == "heard"
    stored = list_vocabulary(language_db, "creator")
    assert len(stored) == 1
    assert stored[0]["state"] == "heard"
    assert get_usable_words(language_db, "creator") == set()

@pytest.mark.parametrize(
    "statement",
    [
        "Est-ce que le mot coq signifie un oiseau domestique ?",
        "Je ne sais pas ce que le mot coq signifie.",
        "Je me demande si coq signifie un oiseau domestique.",
        "Je ne suis pas sûr que coq signifie un oiseau domestique.",
        "Peut-être que coq signifie un oiseau domestique.",
        "Si le mot coq signifie un oiseau domestique, alors ...",
        "Supposons que coq signifie un oiseau domestique.",
        "Imaginons que le mot coq signifie un oiseau domestique.",
    ],
)
def test_questions_and_uncertain_statements_do_not_teach_vocabulary(
    language_db, statement
):
    from learning.language import record_explicit_word_teaching, list_vocabulary

    assert record_explicit_word_teaching(
        language_db, "creator", statement
    ) == []
    assert list_vocabulary(language_db, "creator") == []


def test_explicit_definition_after_unrelated_question_is_still_taught(language_db):
    from learning.language import record_explicit_word_teaching

    taught = record_explicit_word_teaching(
        language_db,
        "creator",
        "Comment vas-tu ? Le mot coq signifie un oiseau domestique.",
    )

    assert [item["word"] for item in taught] == ["coq"]


@pytest.mark.parametrize(
    "statement",
    [
        "Ce n'est pas vrai que le mot coq signifie un oiseau domestique.",
        "Il est faux que coq signifie un oiseau domestique.",
        "Le mot coq signifie peut-être un oiseau domestique.",
        "Coq signifie probablement un oiseau domestique.",
        "On prétend que coq signifie un oiseau domestique.",
        "Selon Julien, coq signifie un oiseau domestique.",
        "Le mot coq ne signifie pas un oiseau domestique.",
        "Coq signifie pas un oiseau domestique.",
        "Le mot coq ne signifie jamais un oiseau domestique.",
        "Je ne pense pas que le mot coq signifie un oiseau domestique.",
        "Je ne crois pas que coq signifie un oiseau domestique.",
        "Je ne dis pas que coq signifie un oiseau domestique.",
        "Le professeur dit que le mot coq signifie un oiseau domestique.",
        "D'après Julien, le mot coq signifie un oiseau domestique.",
        "Je ne suis pas certain que coq signifie un oiseau domestique.",
    ],
)
def test_disputed_or_reported_definitions_are_not_taught(language_db, statement):
    from learning.language import record_explicit_word_teaching, list_vocabulary

    assert record_explicit_word_teaching(
        language_db, "creator", statement
    ) == []
    assert list_vocabulary(language_db, "creator") == []


def test_new_explicit_definition_cannot_silently_replace_existing_meaning(language_db):
    from learning.language import record_explicit_word_teaching, advance_word

    record_explicit_word_teaching(
        language_db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    advance_word(
        language_db, "creator", "coq", "imitated",
        evidence="Imitation observée",
    )
    advance_word(
        language_db, "creator", "coq", "recognized",
        evidence="Reconnaissance validée",
    )

    result = record_explicit_word_teaching(
        language_db, "creator",
        "Le mot coq signifie un animal imaginaire.",
        evidence="Nouvelle déclaration",
    )

    row = language_db.execute(
        "SELECT meaning, state, evidence FROM personal_vocabulary "
        "WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    assert result[0]["meaning"] == "un oiseau domestique"
    assert row["meaning"] == "un oiseau domestique"
    assert row["state"] == "recognized"
    assert row["evidence"] == "Reconnaissance validée"


def test_disputed_definition_cannot_overwrite_an_existing_meaning(language_db):
    from learning.language import record_explicit_word_teaching

    record_explicit_word_teaching(
        language_db,
        "creator",
        "Le mot coq signifie un oiseau domestique.",
    )
    record_explicit_word_teaching(
        language_db,
        "creator",
        "Le mot coq signifie peut-être un animal imaginaire.",
    )

    row = language_db.execute(
        "SELECT meaning, state FROM personal_vocabulary "
        "WHERE user_id=? AND word=?",
        ("creator", "coq"),
    ).fetchone()
    assert row["meaning"] == "un oiseau domestique"
    assert row["state"] == "heard"



def test_confirmed_live_turn_records_merged_exposure_once(language_db):
    from learning.language import record_confirmed_turn_learning

    result = record_confirmed_turn_learning(
        language_db,
        "creator",
        "Le mot montre signifie un objet qui permet de lire l'heure.",
    )

    assert [item["word"] for item in result["heard"]].count("montre") == 1
    assert [item["word"] for item in result["taught"]] == ["montre"]
    row = language_db.execute(
        "SELECT exposure_count, state, meaning FROM personal_vocabulary "
        "WHERE user_id=? AND word=?",
        ("creator", "montre"),
    ).fetchone()
    assert row["exposure_count"] == 1
    assert row["state"] == "heard"
    assert row["meaning"] == "un objet qui permet de lire l'heure"


def test_confirmed_live_turn_does_not_promote_ordinary_words(language_db):
    from learning.language import record_confirmed_turn_learning

    result = record_confirmed_turn_learning(
        language_db, "creator", "Bonjour Chappie, regarde le jardin."
    )

    assert result["heard"]
    assert result["taught"] == []
    assert all(item["state"] == "heard" for item in result["heard"])


def test_french_elisions_expose_the_root_word_without_learning_the_clitic(language_db):
    from learning.language import record_heard_text, list_vocabulary

    recorded = record_heard_text(
        language_db, "creator",
        "L'éléphant d'accord, j'aime qu'on regarde l’éléphant.",
    )

    words = [item["word"] for item in recorded]
    assert words == ["éléphant", "accord", "aime", "on", "regarde"]
    stored = {item["word"] for item in list_vocabulary(language_db, "creator")}
    assert stored == set(words)
    assert "l'éléphant" not in stored
    assert "l'" not in stored


def test_french_elisions_respect_newborn_known_word_gate():
    from learning.language import text_uses_only_allowed_words, gate_spoken_text

    known = {"éléphant", "regarde"}
    assert text_uses_only_allowed_words("L'éléphant regarde.", known)
    assert not text_uses_only_allowed_words("L'éléphant danse.", known)
    assert gate_spoken_text("L'éléphant regarde.", known) == "L'éléphant regarde."
    assert gate_spoken_text("L'éléphant danse.", known) == "L'éléphant."
