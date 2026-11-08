"""V50.45 — integration tests for atomic, idempotent cognitive effects.

All tests use a temporary SQLite database and the production learning/cognition
functions. No Render, Turso, Gemini, secrets, or production data are accessed.
"""
from pathlib import Path
import sqlite3
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.development import (
    init_development_tables,
    record_affective_snapshot,
)
from cognition.event_receipts import init_cognitive_event_receipt_table
from learning.language import (
    init_language_tables,
    record_heard_text,
    record_explicit_word_teaching,
)
from learning.sensory import init_sensory_tables, record_observation


@pytest.fixture
def cognitive_db(tmp_path):
    db = sqlite3.connect(tmp_path / "cognitive-effects.sqlite3")
    db.row_factory = sqlite3.Row
    init_cognitive_event_receipt_table(db)
    init_development_tables(db)
    init_language_tables(db)
    init_sensory_tables(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def _count(db, table, user_id="creator"):
    return db.execute(
        f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)
    ).fetchone()[0]


def test_affective_snapshot_is_written_once_per_event(cognitive_db):
    db = cognitive_db
    first = record_affective_snapshot(
        db, "creator", {"joy": 75, "curiosity": 90},
        source="gemini_live", event_id="turn-001",
    )
    duplicate = record_affective_snapshot(
        db, "creator", {"joy": 75, "curiosity": 90},
        source="gemini_live", event_id="turn-001",
    )
    assert "id" in first
    assert duplicate["duplicate"] is True
    assert _count(db, "affective_history") == 1
    assert db.execute(
        "SELECT COUNT(*) FROM cognitive_event_receipts "
        "WHERE user_id='creator' AND event_id='turn-001' "
        "AND effect_kind='affective_snapshot'"
    ).fetchone()[0] == 1


def test_heard_vocabulary_is_idempotent_and_never_claims_comprehension(cognitive_db):
    db = cognitive_db
    first = record_heard_text(
        db, "creator", "luciole luciole forêt",
        event_id="audio-001",
    )
    replay = record_heard_text(
        db, "creator", "luciole luciole forêt",
        event_id="audio-001",
    )
    assert {item["word"] for item in first} == {"luciole", "forêt"}
    assert replay == []
    assert _count(db, "personal_vocabulary") == 2
    states = {
        row["word"]: row["state"]
        for row in db.execute(
            "SELECT word, state FROM personal_vocabulary WHERE user_id='creator'"
        )
    }
    assert set(states.values()) == {"heard"}


def test_explicit_teaching_replay_does_not_increment_exposure(cognitive_db):
    db = cognitive_db
    statement = "Le mot luciole signifie petit insecte lumineux"
    first = record_explicit_word_teaching(
        db, "creator", statement, event_id="teach-001"
    )
    replay = record_explicit_word_teaching(
        db, "creator", statement, event_id="teach-001"
    )
    assert len(first) == 1
    assert replay == []
    row = db.execute(
        "SELECT meaning, state, exposure_count FROM personal_vocabulary "
        "WHERE user_id='creator' AND word='luciole'"
    ).fetchone()
    assert row["meaning"] == "petit insecte lumineux"
    assert row["state"] == "heard"
    assert row["exposure_count"] == 1


def test_same_sensory_event_returns_the_original_observation(cognitive_db):
    db = cognitive_db
    first = record_observation(
        db, "creator", "audio", "Bonjour Chappie", "gemini_live",
        confidence=0.8, metadata={"language": "fr"}, event_id="audio-002",
    )
    replay = record_observation(
        db, "creator", "audio", "Bonjour Chappie", "gemini_live",
        confidence=0.8, metadata={"language": "fr"}, event_id="audio-002",
    )
    assert first["observation_id"] == replay["observation_id"]
    assert _count(db, "sensory_observations") == 1
    assert db.execute(
        "SELECT COUNT(*) FROM cognitive_event_receipts "
        "WHERE user_id='creator' AND event_id='audio-002' "
        "AND effect_kind='sensory_observation_audio'"
    ).fetchone()[0] == 1


def test_identical_content_from_distinct_events_remains_two_observations(cognitive_db):
    db = cognitive_db
    a = record_observation(
        db, "creator", "vision", "Une tasse bleue", "camera",
        event_id="vision-001",
    )
    b = record_observation(
        db, "creator", "vision", "Une tasse bleue", "camera",
        event_id="vision-002",
    )
    assert a["observation_id"] != b["observation_id"]
    assert _count(db, "sensory_observations") == 2


def test_receipt_and_all_effects_rollback_together(cognitive_db):
    db = cognitive_db
    db.execute("BEGIN")
    record_affective_snapshot(
        db, "creator", {"joy": 60}, event_id="atomic-turn-1"
    )
    record_heard_text(
        db, "creator", "papillon", event_id="atomic-turn-1"
    )
    observation = record_observation(
        db, "creator", "audio", "Un papillon passe",
        "gemini_live", event_id="atomic-turn-1",
    )
    assert observation["observation_id"]
    db.rollback()

    assert _count(db, "affective_history") == 0
    assert _count(db, "personal_vocabulary") == 0
    assert _count(db, "sensory_observations") == 0
    assert db.execute(
        "SELECT COUNT(*) FROM cognitive_event_receipts "
        "WHERE user_id='creator' AND event_id='atomic-turn-1'"
    ).fetchone()[0] == 0

    # A retry after rollback must be able to claim and persist every effect.
    db.execute("BEGIN")
    record_affective_snapshot(
        db, "creator", {"joy": 60}, event_id="atomic-turn-1"
    )
    record_heard_text(
        db, "creator", "papillon", event_id="atomic-turn-1"
    )
    record_observation(
        db, "creator", "audio", "Un papillon passe",
        "gemini_live", event_id="atomic-turn-1",
    )
    db.commit()
    assert _count(db, "affective_history") == 1
    assert _count(db, "personal_vocabulary") == 1
    assert _count(db, "sensory_observations") == 1


def test_effect_receipts_are_scoped_by_user_and_effect(cognitive_db):
    db = cognitive_db
    record_affective_snapshot(
        db, "creator", {"joy": 10}, event_id="shared-event"
    )
    record_affective_snapshot(
        db, "second-user", {"joy": 10}, event_id="shared-event"
    )
    record_heard_text(
        db, "creator", "étoile", event_id="shared-event"
    )
    assert _count(db, "affective_history", "creator") == 1
    assert _count(db, "affective_history", "second-user") == 1
    assert _count(db, "personal_vocabulary", "creator") == 1
    assert db.execute(
        "SELECT COUNT(*) FROM cognitive_event_receipts "
        "WHERE event_id='shared-event'"
    ).fetchone()[0] == 3
