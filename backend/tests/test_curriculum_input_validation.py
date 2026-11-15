"""Strict input validation for Chappie's cognitive curriculum."""
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from learning.curriculum import (
    init_learning_tables,
    evaluate_competency_test,
    get_competency_test_history,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_learning_tables(db)
    return db


def test_competency_score_rejects_coerced_and_non_finite_values():
    db = make_db()
    for score in ("90", True, None, {}, [], float("nan"), float("inf")):
        try:
            evaluate_competency_test(db, "creator", "test", True, score)
            assert False, f"Score invalide accepté: {score!r}"
        except ValueError:
            pass
    assert db.execute("SELECT COUNT(*) FROM competency_tests").fetchone()[0] == 0
    db.close()


def test_competency_maturity_and_user_validation_remain_strict():
    db = make_db()
    for user in (None, "", " ", 7, True, {}, []):
        try:
            get_competency_test_history(db, user)
            assert False, f"Utilisateur invalide accepté: {user!r}"
        except ValueError:
            pass
    for maturity in ("3", True, None, {}, [], float("nan"), float("inf")):
        try:
            from learning.curriculum import update_cognitive_milestones
            update_cognitive_milestones(db, "creator", maturity)
            assert False, f"Maturité invalide acceptée: {maturity!r}"
        except ValueError:
            pass
    db.close()


def test_competency_history_uses_strict_integer_limit():
    db = make_db()
    evaluate_competency_test(db, "creator", "test", True, 90)
    assert len(get_competency_test_history(db, "creator", 1)) == 1
    for limit in (0, -1, True, 1.5, "10", None):
        try:
            get_competency_test_history(db, "creator", limit)
            assert False, f"Limite invalide acceptée: {limit!r}"
        except ValueError:
            pass
    assert len(get_competency_test_history(db, "creator")) == 1
    db.close()
