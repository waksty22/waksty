"""Regression: shared-brain learning survives a full SQLite connection reopen."""

from pathlib import Path
import sqlite3
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cognition.shared_brain import get_shared_brain_snapshot
from learning.language import init_language_tables, record_heard_word
from learning.sensory import init_sensory_tables, record_observation


def test_shared_brain_learning_survives_database_reopen(tmp_path):
    database_path = tmp_path / "shared-brain.sqlite3"

    first = sqlite3.connect(database_path)
    first.row_factory = sqlite3.Row
    try:
        init_language_tables(first)
        init_sensory_tables(first)
        first.executescript("""
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY, user_id TEXT, category TEXT, content TEXT,
                importance INTEGER, tags TEXT, access_count INTEGER,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY, user_id TEXT, skill_name TEXT, level REAL,
                evidence TEXT, updated_at TEXT
            );
            CREATE TABLE emotional_state (
                user_id TEXT, joy REAL, fear REAL, curiosity REAL,
                frustration REAL, sadness REAL, energy REAL, updated_at TEXT
            );
        """)
        record_heard_word(first, "creator", "pomme", "Mot entendu pendant le chat")
        observation = record_observation(
            first, "creator", "vision", "Une forme rouge observée.",
            "regression_test", confidence=0.7,
        )
        first.commit()
        assert observation["observation_id"]
    finally:
        first.close()

    # A genuinely new connection simulates the database handle being lost
    # during a process restart; no in-memory state is reused.
    second = sqlite3.connect(database_path)
    second.row_factory = sqlite3.Row
    try:
        snapshot = get_shared_brain_snapshot(second, "creator")
        assert any(
            item["word"] == "pomme" and item["state"] == "heard"
            for item in snapshot["vocabulary"]
        )
        assert any(
            item["modality"] == "vision"
            and item["source"] == "regression_test"
            for item in snapshot["sensory_observations"]
        )
        assert snapshot["rules"]["observed_is_not_understood"] is True
    finally:
        second.close()
