import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learning.supervised_learning import (
    init_supervised_learning_tables,
    record_demonstration,
    record_practice,
    validate_imitation,
    reject_imitation,
    list_imitation_learning,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_supervised_learning_tables(connection)
    yield connection
    connection.close()


def demonstration(db, user="creator"):
    return record_demonstration(
        db, user, "saluer en levant la main",
        "Le créateur montre le geste devant la caméra.",
        source_type="demonstrated",
        context="Démonstration filmée",
    )


def test_demonstration_is_only_observed_initially(db):
    item = demonstration(db)
    assert item["status"] == "observed"
    assert item["supervisor_approved"] is False


def test_demonstration_requires_evidence(db):
    with pytest.raises(ValueError):
        record_demonstration(db, "creator", "saluer", "")


def test_user_cannot_practice_another_users_demonstration(db):
    item = demonstration(db, "alice")
    with pytest.raises(ValueError):
        record_practice(
            db, "bob", item["id"], "geste reproduit",
            "aucune preuve", True,
        )


def test_validation_requires_supervisor_approval(db):
    item = demonstration(db)
    record_practice(
        db, "creator", item["id"], "geste reproduit",
        "La vidéo montre le geste reproduit.", True,
    )
    with pytest.raises(ValueError):
        validate_imitation(
            db, "creator", item["id"], False, "Validation refusée"
        )


def test_validation_requires_successful_practice(db):
    item = demonstration(db)
    with pytest.raises(ValueError):
        validate_imitation(
            db, "creator", item["id"], True, "Validation prématurée"
        )
    record_practice(
        db, "creator", item["id"], "geste non reproduit",
        "La main ne s'est pas levée.", False,
    )
    with pytest.raises(ValueError):
        validate_imitation(
            db, "creator", item["id"], True, "Aucune réussite observée"
        )


def test_validated_imitation_needs_practice_and_approval(db):
    item = demonstration(db)
    record_practice(
        db, "creator", item["id"], "geste reproduit",
        "La séquence montre une reproduction correcte.", True,
    )
    result = validate_imitation(
        db, "creator", item["id"], True,
        "Le créateur confirme la reproduction.",
    )
    assert result["status"] == "validated"
    state = list_imitation_learning(db, "creator")
    assert state["statistics"]["validated"] == 1
    assert state["examples"][0]["supervisor_approved"] == 1


def test_rejected_imitation_cannot_be_rejected_or_rewritten_again(db):
    item = demonstration(db)
    first = reject_imitation(
        db, "creator", item["id"], "Démonstration incorrecte"
    )
    before = db.execute(
        "SELECT status,evidence,updated_at FROM imitation_examples WHERE id=?",
        (item["id"],),
    ).fetchone()
    with pytest.raises(ValueError, match="clôturée"):
        reject_imitation(
            db, "creator", item["id"], "Deuxième motif qui ne doit pas s'ajouter"
        )
    after = db.execute(
        "SELECT status,evidence,updated_at FROM imitation_examples WHERE id=?",
        (item["id"],),
    ).fetchone()
    assert first["status"] == "rejected"
    assert tuple(after) == tuple(before)
    assert after["evidence"].count("Rejet :") == 1


def test_rejected_imitation_cannot_be_practiced(db):
    item = demonstration(db)
    reject_imitation(db, "creator", item["id"], "Démonstration incorrecte")
    with pytest.raises(ValueError):
        record_practice(
            db, "creator", item["id"], "tentative",
            "preuve", True,
        )


def test_dashboard_is_scoped_to_user(db):
    demonstration(db, "alice")
    state = list_imitation_learning(db, "bob")
    assert state["examples"] == []
    assert state["total"] == 0



@pytest.mark.parametrize("bad", [None, "", "   ", 7, True, {}, []])
def test_demonstration_rejects_invalid_user_id_without_writing(db, bad):
    with pytest.raises(ValueError):
        record_demonstration(db, bad, "saluer", "preuve")
    assert db.execute("SELECT COUNT(*) FROM imitation_examples").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [None, 7, True, {}, []])
def test_demonstration_rejects_non_text_context_without_writing(db, bad):
    with pytest.raises(ValueError):
        record_demonstration(db, "creator", "saluer", "preuve", context=bad)
    assert db.execute("SELECT COUNT(*) FROM imitation_examples").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1", None])
def test_practice_rejects_invalid_example_id(db, bad):
    with pytest.raises(ValueError):
        record_practice(db, "creator", bad, "résultat", "preuve", True)
    assert db.execute("SELECT COUNT(*) FROM imitation_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10", None])
def test_imitation_listing_rejects_invalid_limit(db, bad):
    with pytest.raises(ValueError):
        list_imitation_learning(db, "creator", limit=bad)
