import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from learning.language import (
    advance_word,
    correct_word_definition,
    init_language_tables,
    record_explicit_word_teaching,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_language_tables(connection)
    yield connection
    connection.close()


def test_explicit_correction_updates_current_definition_and_keeps_history(db):
    record_explicit_word_teaching(
        db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    advance_word(
        db, "creator", "coq", "imitated",
        evidence="Chappie a répété le mot après le créateur.",
    )
    advance_word(
        db, "creator", "coq", "recognized",
        evidence="Le créateur a validé la reconnaissance du mot.",
    )

    corrected = correct_word_definition(
        db, "creator", "coq", "Un oiseau mâle de la famille des gallinacés.",
        "Correction explicite du créateur après vérification de la définition.",
    )

    current = db.execute(
        "SELECT meaning, state, evidence, exposure_count FROM personal_vocabulary WHERE user_id='creator' AND word='coq'"
    ).fetchone()
    history = db.execute(
        "SELECT previous_meaning, corrected_meaning, previous_evidence, correction_evidence FROM personal_vocabulary_history WHERE user_id='creator' AND word='coq'"
    ).fetchall()

    assert current["meaning"] == "Un oiseau mâle de la famille des gallinacés."
    assert current["state"] == "recognized"
    assert current["exposure_count"] == 1
    assert current["evidence"] == "Correction explicite du créateur après vérification de la définition."
    assert len(history) == 1
    assert history[0]["previous_meaning"] == "un oiseau domestique"
    assert history[0]["corrected_meaning"] == current["meaning"]
    assert history[0]["previous_evidence"] == "Le créateur a validé la reconnaissance du mot."
    assert corrected["history_preserved"] is True
    assert corrected["previous_meaning"] == "un oiseau domestique"


def test_correction_is_user_scoped_and_does_not_touch_other_vocabulary(db):
    record_explicit_word_teaching(
        db, "creator", "Le mot montre signifie un objet qui permet de lire l'heure."
    )
    with pytest.raises(ValueError, match="enseigné"):
        correct_word_definition(
            db, "another-user", "montre", "Un autre sens.",
            "Le créateur confirme explicitement cette nouvelle définition.",
        )
    assert db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary_history"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "meaning,evidence",
    [
        ("", "Le créateur confirme explicitement cette nouvelle définition."),
        ("Nouveau sens", "trop court"),
        ("Nouveau sens", None),
        ("Nouveau sens", 42),
    ],
)
def test_invalid_correction_is_rejected_without_changing_current_meaning(
    db, meaning, evidence
):
    record_explicit_word_teaching(
        db, "creator", "Le mot montre signifie un objet qui permet de lire l'heure."
    )
    with pytest.raises(ValueError):
        correct_word_definition(db, "creator", "montre", meaning, evidence)
    row = db.execute(
        "SELECT meaning FROM personal_vocabulary WHERE user_id='creator' AND word='montre'"
    ).fetchone()
    assert row["meaning"] == "un objet qui permet de lire l'heure"
    assert db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary_history"
    ).fetchone()[0] == 0


def test_identical_definition_cannot_create_fake_correction(db):
    record_explicit_word_teaching(
        db, "creator", "Le mot coq signifie un oiseau domestique."
    )
    with pytest.raises(ValueError, match="identique"):
        correct_word_definition(
            db, "creator", "coq", "un oiseau domestique",
            "Le créateur confirme explicitement cette même définition.",
        )
    assert db.execute(
        "SELECT COUNT(*) FROM personal_vocabulary_history"
    ).fetchone()[0] == 0
