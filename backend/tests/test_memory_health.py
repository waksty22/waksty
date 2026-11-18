import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.memory_health import inspect_memory_persistence


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE conversations (id INTEGER, user_id TEXT, role TEXT, content TEXT, created_at TEXT);
        CREATE TABLE conversation_summaries (id INTEGER, user_id TEXT, summary TEXT);
        CREATE TABLE journal (id INTEGER, user_id TEXT, entry TEXT);
        CREATE TABLE memories (id INTEGER, user_id TEXT, content TEXT);
        CREATE TABLE memories_v19 (id INTEGER, user_id TEXT, content TEXT);
        CREATE TABLE autobiographical_events (id INTEGER, user_id TEXT, content TEXT);
        CREATE TABLE autobiographical_links (id INTEGER, user_id TEXT);
        INSERT INTO conversations VALUES (1, 'creator', 'user', 'private text', 't1');
        INSERT INTO conversations VALUES (2, 'other', 'user', 'other text', 't1');
        INSERT INTO memories_v19 VALUES (1, 'creator', 'remembered');
        INSERT INTO autobiographical_events VALUES (1, 'creator', 'episode');
    """)
    return db


def test_memory_health_reports_active_backend_and_user_scoped_counts():
    db = make_db()
    report = inspect_memory_persistence(db, "creator", "sqlite")
    assert report["backend"] == "sqlite"
    assert report["read_only"] is True
    assert report["schema_ready"] is True
    assert report["conversation_rows"] == 1
    assert report["episodic_memory_rows"] == 1
    assert report["autobiographical_event_rows"] == 1
    assert "private text" not in repr(report)
    assert "other text" not in repr(report)
    db.close()


def test_memory_health_reports_missing_tables_without_writing():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE conversations (id INTEGER, user_id TEXT)")
    before = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    report = inspect_memory_persistence(db, "creator", "sqlite")
    after = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert report["schema_ready"] is False
    assert "memories_v19" in report["missing_tables"]
    assert before == after
    db.close()
