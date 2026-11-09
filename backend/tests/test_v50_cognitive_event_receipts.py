"""V50.37 — tests for the shared cognitive event receipt primitive."""
import sqlite3
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.event_receipts import claim_cognitive_event


def database(tmp_path):
    db = sqlite3.connect(tmp_path / "event-receipts.sqlite3")
    db.row_factory = sqlite3.Row
    return db


def test_same_user_event_and_effect_can_be_claimed_only_once(tmp_path):
    with database(tmp_path) as db:
        assert claim_cognitive_event(db, "creator", "live-turn-1", "affect") is True
        assert claim_cognitive_event(db, "creator", "live-turn-1", "affect") is False
        count = db.execute(
            "SELECT COUNT(*) FROM cognitive_event_receipts"
        ).fetchone()[0]
    assert count == 1


def test_same_event_can_protect_different_effect_kinds(tmp_path):
    with database(tmp_path) as db:
        assert claim_cognitive_event(db, "creator", "event-1", "affect") is True
        assert claim_cognitive_event(db, "creator", "event-1", "vocabulary") is True
        assert claim_cognitive_event(db, "creator", "event-1", "sensory") is True
        count = db.execute(
            "SELECT COUNT(*) FROM cognitive_event_receipts"
        ).fetchone()[0]
    assert count == 3


def test_event_ids_are_isolated_between_users(tmp_path):
    with database(tmp_path) as db:
        assert claim_cognitive_event(db, "creator", "event-1", "affect") is True
        assert claim_cognitive_event(db, "second-user", "event-1", "affect") is True
        assert claim_cognitive_event(db, "creator", "event-1", "affect") is False


def test_missing_event_id_keeps_legacy_non_deduplicated_behavior(tmp_path):
    with database(tmp_path) as db:
        assert claim_cognitive_event(db, "creator", None, "affect") is True
        assert claim_cognitive_event(db, "creator", "", "affect") is True
        count = db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='cognitive_event_receipts'"
        ).fetchone()[0]
    assert count == 0


def test_receipt_rolls_back_with_its_side_effect_transaction(tmp_path):
    db = database(tmp_path)
    try:
        db.execute("BEGIN")
        assert claim_cognitive_event(db, "creator", "event-rollback", "affect") is True
        db.execute("CREATE TABLE IF NOT EXISTS sample_effects (value TEXT)")
        db.execute("INSERT INTO sample_effects(value) VALUES ('effect')")
        db.rollback()

        assert claim_cognitive_event(db, "creator", "event-rollback", "affect") is True
        count = db.execute(
            "SELECT COUNT(*) FROM cognitive_event_receipts"
        ).fetchone()[0]
        effect_table = db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='sample_effects'"
        ).fetchone()[0]
        assert count == 1
        assert effect_table == 0
    finally:
        db.close()


def test_invalid_scope_is_rejected(tmp_path):
    with database(tmp_path) as db:
        try:
            claim_cognitive_event(db, "", "event-1", "affect")
        except ValueError as exc:
            assert "user_id" in str(exc)
        else:
            raise AssertionError("Missing user_id should be rejected")
        try:
            claim_cognitive_event(db, "creator", "event-1", "")
        except ValueError as exc:
            assert "effect_kind" in str(exc)
        else:
            raise AssertionError("Missing effect_kind should be rejected")
