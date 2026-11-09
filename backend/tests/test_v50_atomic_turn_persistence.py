"""V50.39 — atomic conversation/cognitive persistence contracts."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest
import server
from cognition.development import init_development_tables, record_affective_snapshot
from cognition.event_receipts import init_cognitive_event_receipt_table
from learning.language import init_language_tables, record_heard_text
from learning.sensory import init_sensory_tables, record_observation


@pytest.fixture
def atomic_db(tmp_path, monkeypatch):
    path = tmp_path / "atomic-turn.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                entry TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        init_development_tables(db)
        init_language_tables(db)
        init_sensory_tables(db)
        init_cognitive_event_receipt_table(db)
        db.commit()

    @contextmanager
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(server, "db_connection", connect)
    monkeypatch.setattr(server, "valid_user", lambda value: value)
    return connect


def apply_test_turn(db, event_id):
    saved = server.save_conversation_turn(
        "creator", "J'entends une luciole.", "Je retiens ce tour.",
        source="gemini_live", turn_id=event_id, db=db,
    )
    if not saved:
        return False
    record_heard_text(db, "creator", "luciole", event_id=event_id)
    record_affective_snapshot(
        db, "creator",
        {"joy": 10, "fear": 0, "curiosity": 20,
         "frustration": 0, "sadness": 0, "energy": 99},
        source="gemini_live", event_id=event_id,
    )
    record_observation(
        db, "creator", "audio", "J'entends une luciole.",
        "gemini_live_transcription", event_id=event_id,
    )
    return True


def test_all_turn_and_cognitive_writes_rollback_together(atomic_db):
    with pytest.raises(RuntimeError):
        with atomic_db() as db:
            assert apply_test_turn(db, "atomic-turn-0001")
            raise RuntimeError("simulated failure before commit")

    with atomic_db() as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM conversation_turn_receipts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM cognitive_event_receipts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM personal_vocabulary").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM affective_history").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 0


def test_conversation_and_effects_commit_as_one_unit(atomic_db, monkeypatch):
    def forbidden_finalize(_user_id):
        raise AssertionError("post-commit finalizer must not run inside caller transaction")

    monkeypatch.setattr(server, "finalize_conversation_turn", forbidden_finalize)
    with atomic_db() as db:
        assert apply_test_turn(db, "atomic-turn-0002")

    with atomic_db() as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM conversation_turn_receipts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM cognitive_event_receipts").fetchone()[0] == 3
        assert db.execute("SELECT exposure_count FROM personal_vocabulary WHERE word='luciole'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM affective_history").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 1


def test_replayed_turn_does_not_reapply_any_cognitive_effect(atomic_db):
    with atomic_db() as db:
        assert apply_test_turn(db, "atomic-turn-0003")
    with atomic_db() as db:
        assert apply_test_turn(db, "atomic-turn-0003") is False

    with atomic_db() as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 2
        assert db.execute("SELECT exposure_count FROM personal_vocabulary WHERE word='luciole'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM affective_history").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 1


def test_same_content_in_distinct_turns_remains_two_experiences(atomic_db):
    with atomic_db() as db:
        assert apply_test_turn(db, "atomic-turn-0004")
    with atomic_db() as db:
        assert apply_test_turn(db, "atomic-turn-0005")

    with atomic_db() as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 4
        assert db.execute("SELECT exposure_count FROM personal_vocabulary WHERE word='luciole'").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM affective_history").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM sensory_observations").fetchone()[0] == 2
