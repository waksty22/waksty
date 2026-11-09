"""V50.36 — reproducible audit of learning side effects on duplicate delivery.

These tests deliberately document current duplicate behavior in isolated SQLite.
They are regression probes for the audit and should be inverted when V50.37
introduces event-level idempotency.
"""
from pathlib import Path
import sqlite3
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from cognition.development import init_development_tables, record_affective_snapshot
from learning.language import (
    init_language_tables,
    record_explicit_word_teaching,
    record_heard_text,
)
from learning.sensory import init_sensory_tables, record_observation


def isolated_db(tmp_path):
    db = sqlite3.connect(tmp_path / "side-effects.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    init_development_tables(db)
    init_language_tables(db)
    init_sensory_tables(db)
    db.commit()
    return db


def test_duplicate_affective_event_creates_two_history_rows(tmp_path):
    with isolated_db(tmp_path) as db:
        state = {"joy": 50, "fear": 0, "curiosity": 70,
                 "frustration": 0, "sadness": 0, "energy": 100}
        record_affective_snapshot(
            db, "creator", state, source="gemini_live",
            event_label="transcription utilisateur",
        )
        record_affective_snapshot(
            db, "creator", state, source="gemini_live",
            event_label="transcription utilisateur",
        )
        count = db.execute(
            "SELECT COUNT(*) FROM affective_history WHERE user_id='creator'"
        ).fetchone()[0]
    assert count == 2  # Current gap: no event_id / unique receipt.


def test_duplicate_heard_transcription_increments_exposure_twice(tmp_path):
    with isolated_db(tmp_path) as db:
        record_heard_text(db, "creator", "bonjour luciole", evidence="Live")
        record_heard_text(db, "creator", "bonjour luciole", evidence="Live")
        counts = dict(db.execute(
            "SELECT word, exposure_count FROM personal_vocabulary "
            "WHERE user_id='creator'"
        ).fetchall())
    assert counts == {"bonjour": 2, "luciole": 2}


def test_duplicate_explicit_teaching_increments_exposure_twice(tmp_path):
    with isolated_db(tmp_path) as db:
        teaching = "luciole signifie petit insecte lumineux"
        record_explicit_word_teaching(db, "creator", teaching, evidence="Live")
        record_explicit_word_teaching(db, "creator", teaching, evidence="Live")
        row = db.execute(
            "SELECT exposure_count, meaning FROM personal_vocabulary "
            "WHERE user_id='creator' AND word='luciole'"
        ).fetchone()
    assert row["exposure_count"] == 2
    assert row["meaning"] == "petit insecte lumineux"


def test_replayed_sensory_observation_creates_distinct_rows(tmp_path):
    with isolated_db(tmp_path) as db:
        first = record_observation(
            db, "creator", "audio", "bonjour luciole",
            "gemini_live_transcription", confidence=0.8,
        )
        second = record_observation(
            db, "creator", "audio", "bonjour luciole",
            "gemini_live_transcription", confidence=0.8,
        )
        count = db.execute(
            "SELECT COUNT(*) FROM sensory_observations WHERE user_id='creator'"
        ).fetchone()[0]
    assert first["observation_id"] != second["observation_id"]
    assert count == 2  # Current gap: every replay gets a fresh random UUID.
