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
        CREATE TABLE conversation_finalization_outbox (
            id INTEGER, user_id TEXT, through_conversation_id INTEGER,
            status TEXT, attempts INTEGER, last_error TEXT
        );
        INSERT INTO conversations VALUES (1, 'creator', 'user', 'private text', 't1');
        INSERT INTO conversations VALUES (2, 'other', 'user', 'other text', 't1');
        INSERT INTO memories_v19 VALUES (1, 'creator', 'remembered');
        INSERT INTO autobiographical_events VALUES (1, 'creator', 'episode');
        INSERT INTO conversation_finalization_outbox
            VALUES (1, 'creator', 12, 'pending', 1, 'private error detail');
        INSERT INTO conversation_finalization_outbox
            VALUES (2, 'other', 14, 'completed', 2, '');
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
    assert report["pending_finalization_jobs"] == 1
    assert report["failed_finalization_jobs"] == 1
    assert "private error detail" not in repr(report)
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


def test_active_memory_count_uses_v19_and_scopes_by_user():
    from storage.memory_health import count_active_episodic_memories

    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE memories (id INTEGER, user_id TEXT, content TEXT);
        CREATE TABLE memories_v19 (id INTEGER, user_id TEXT, content TEXT);
        INSERT INTO memories VALUES (1, 'creator', 'legacy one');
        INSERT INTO memories VALUES (2, 'creator', 'legacy two');
        INSERT INTO memories_v19 VALUES (1, 'creator', 'active one');
        INSERT INTO memories_v19 VALUES (2, 'creator', 'active two');
        INSERT INTO memories_v19 VALUES (3, 'other', 'other user');
    """)
    assert count_active_episodic_memories(db, "creator") == 2
    assert count_active_episodic_memories(db, "other") == 1
    assert count_active_episodic_memories(db, "missing") == 0
    db.close()


def test_active_memory_count_rejects_empty_user_id():
    from storage.memory_health import count_active_episodic_memories

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE memories_v19 (id INTEGER, user_id TEXT)")
    try:
        count_active_episodic_memories(db, " ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty user id must be rejected")
    db.close()


def test_core_memory_readiness_does_not_depend_on_optional_outbox_table():
    db = make_db()
    db.execute("DROP TABLE conversation_finalization_outbox")
    report = inspect_memory_persistence(db, "creator", "sqlite")
    assert report["schema_ready"] is True
    assert report["pending_finalization_jobs"] is None
    assert report["failed_finalization_jobs"] is None
    db.close()
