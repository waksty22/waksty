import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.development import (
    evaluate_decision,
    init_development_tables,
    record_decision,
)


@pytest.fixture
def development_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_development_tables(db)
    yield db
    db.close()


def test_evaluated_decision_outcome_cannot_be_silently_overwritten(development_db):
    decision = record_decision(
        development_db,
        "creator",
        "Quelle méthode choisir ?",
        ["A", "B"],
        chosen_option="A",
        reasons="Option A est mieux étayée.",
        evidence=["Comparaison initiale"],
    )
    first = evaluate_decision(
        development_db,
        "creator",
        decision["id"],
        "Le résultat observé confirme partiellement A.",
    )
    assert first["status"] == "evaluated"

    with pytest.raises(ValueError, match="résultat initial ne peut pas être écrasé"):
        evaluate_decision(
            development_db,
            "creator",
            decision["id"],
            "Nouveau résultat contradictoire.",
            revised_choice="B",
        )

    row = development_db.execute(
        "SELECT outcome, chosen_option, status FROM decision_journal WHERE id=?",
        (decision["id"],),
    ).fetchone()
    assert row["outcome"] == "Le résultat observé confirme partiellement A."
    assert row["chosen_option"] == "A"
    assert row["status"] == "evaluated"


def test_decision_can_be_revised_once_before_final_evaluation(development_db):
    decision = record_decision(
        development_db,
        "creator",
        "Quel test effectuer ?",
        ["simulation", "test contrôlé"],
        chosen_option="simulation",
    )
    revised = evaluate_decision(
        development_db,
        "creator",
        decision["id"],
        "La simulation ne permet pas de trancher.",
        revised_choice="test contrôlé",
    )
    assert revised["status"] == "revised"
    assert revised["chosen_option"] == "test contrôlé"

    with pytest.raises(ValueError, match="résultat initial ne peut pas être écrasé"):
        evaluate_decision(
            development_db,
            "creator",
            decision["id"],
            "Nouvelle tentative d'écrasement.",
        )
