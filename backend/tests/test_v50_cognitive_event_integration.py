"""V50.38 — integration tests for event-idempotent cognitive side effects."""
import sqlite3
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.development import init_development_tables, record_affective_snapshot
from learning.language import (
    init_language_tables, record_heard_text, record_explicit_word_teaching,
)
from learning.sensory import init_sensory_tables, record_observation


def cognitive_db(tmp_path):
    db = sqlite3.connect(tmp_path / "cognitive-effects.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    init_development_tables(db)
    init_language_tables(db)
    init_sensory_tables(db)
    db.commit()
    return db


def test_affective_snapshot_is_written_once_for_same_event(tmp_path):
    with cognitive_db(tmp_path) as db:
        state = {"joy": 50, "fear": 0, "curiosity": 70,
                 "frustration": 0, "sadness": 0, "energy": 100}
        first = record_affective_snapshot(
            db, "creator", state, source="gemini_live",
            event_label="tour terminé", event_id="turn-0001",
        )
        replay = record_affective_snapshot(
            db, "creator", state, source="gemini_live",
            event_label="tour terminé", event_id="turn-0001",
        )
        count = db.execute(
            "SELECT COUNT(*) FROM affective_history WHERE user_id='creator'"
        ).fetchone()[0]
    assert first["id"] > 0
    assert replay["duplicate"] is True
    assert count == 1


def test_heard_vocabulary_effect_is_once_per_event_but_new_turn_counts_again(tmp_path):
    with cognitive_db(tmp_path) as db:
        first = record_heard_text(
            db, "creator", "bonjour luciole", event_id="turn-0001"
        )
        replay = record_heard_text(
            db, "creator", "bonjour luciole", event_id="turn-0001"
        )
        next_turn = record_heard_text(
            db, "creator", "bonjour luciole", event_id="turn-0002"
        )
        exposures = dict(db.execute(
            "SELECT word, exposure_count FROM personal_vocabulary "
            "WHERE user_id='creator'"
        ).fetchall())
    assert len(first) == 2
    assert replay == []
    assert len(next_turn) == 2
    assert exposures == {"bonjour": 2, "luciole": 2}


def test_explicit_teaching_is_once_per_event(tmp_path):
    with cognitive_db(tmp_path) as db:
        text = "Le mot luciole signifie petit insecte lumineux"
        first = record_explicit_word_teaching(
            db, "creator", text, event_id="turn-0001"
        )
        replay = record_explicit_word_teaching(
            db, "creator", text, event_id="turn-0001"
        )
        row = db.execute(
            "SELECT exposure_count, meaning FROM personal_vocabulary "
            "WHERE user_id='creator' AND word='luciole'"
        ).fetchone()
    assert len(first) == 1
    assert replay == []
    assert row["exposure_count"] == 1
    assert row["meaning"] == "petit insecte lumineux"


def test_sensory_observation_is_stable_and_not_duplicated(tmp_path):
    with cognitive_db(tmp_path) as db:
        first = record_observation(
            db, "creator", "audio", "bonjour luciole",
            "gemini_live_transcription", confidence=0.8,
            event_id="turn-0001",
        )
        replay = record_observation(
            db, "creator", "audio", "bonjour luciole",
            "gemini_live_transcription", confidence=0.8,
            event_id="turn-0001",
        )
        count = db.execute(
            "SELECT COUNT(*) FROM sensory_observations WHERE user_id='creator'"
        ).fetchone()[0]
    assert first["observation_id"] == replay["observation_id"]
    assert count == 1


def test_same_words_in_two_real_events_are_not_collapsed(tmp_path):
    with cognitive_db(tmp_path) as db:
        a = record_observation(
            db, "creator", "audio", "oui",
            "gemini_live_transcription", event_id="turn-0001",
        )
        b = record_observation(
            db, "creator", "audio", "oui",
            "gemini_live_transcription", event_id="turn-0002",
        )
        count = db.execute(
            "SELECT COUNT(*) FROM sensory_observations WHERE user_id='creator'"
        ).fetchone()[0]
    assert a["observation_id"] != b["observation_id"]
    assert count == 2


def test_receipt_and_cognitive_effect_rollback_together(tmp_path):
    db = cognitive_db(tmp_path)
    try:
        db.execute("BEGIN")
        record_heard_text(
            db, "creator", "luciole", event_id="turn-rollback"
        )
        db.rollback()

        db.execute("BEGIN")
        recorded = record_heard_text(
            db, "creator", "luciole", event_id="turn-rollback"
        )
        db.commit()
        exposure = db.execute(
            "SELECT exposure_count FROM personal_vocabulary "
            "WHERE user_id='creator' AND word='luciole'"
        ).fetchone()[0]
    finally:
        db.close()
    assert len(recorded) == 1
    assert exposure == 1
