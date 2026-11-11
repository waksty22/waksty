import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.global_persistence import inspect_global_persistence


def _db(with_extra_table=False):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL
        );
        INSERT INTO conversations VALUES (1, 'creator', 'private conversation');
        INSERT INTO conversations VALUES (2, 'other', 'other conversation');
        INSERT INTO memories VALUES (1, 'creator', 'private memory');
    """)
    if with_extra_table:
        db.execute("CREATE TABLE turso_only (id INTEGER PRIMARY KEY)")
    return db


def test_global_audit_compares_both_stores_and_scopes_counts():
    sqlite_db = _db()
    turso_db = _db(with_extra_table=True)
    report = inspect_global_persistence(
        sqlite_db, turso_db, "sqlite", "creator"
    )

    assert report["read_only"] is True
    assert report["active_backend"] == "sqlite"
    assert report["sqlite"]["table_count"] == 2
    assert report["sqlite"]["total_rows"] == 3
    assert report["sqlite"]["tables"]["conversations"]["rows_total"] == 2
    assert report["sqlite"]["tables"]["conversations"]["rows_for_authenticated_user"] == 1
    assert report["comparison"]["missing_tables_in_turso"] == []
    assert report["comparison"]["extra_tables_in_turso"] == ["turso_only"]
    assert "private conversation" not in repr(report)
    assert "private memory" not in repr(report)

    sqlite_db.close()
    turso_db.close()


def test_global_audit_reports_unavailable_turso_without_mutation():
    sqlite_db = _db()
    before = sqlite_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    report = inspect_global_persistence(
        sqlite_db, None, "sqlite", "creator", turso_status="not_configured"
    )

    after = sqlite_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    assert report["comparison"]["available"] is False
    assert report["comparison"]["status"] == "not_configured"
    assert before == after

    sqlite_db.close()


def test_global_audit_detects_schema_drift_without_exposing_ddl():
    sqlite_db = _db()
    turso_db = sqlite3.connect(":memory:")
    turso_db.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id TEXT, content TEXT, extra TEXT)"
    )
    turso_db.execute(
        "CREATE TABLE memories (id INTEGER PRIMARY KEY, user_id TEXT, content TEXT)"
    )

    report = inspect_global_persistence(
        sqlite_db, turso_db, "sqlite", "creator"
    )

    assert report["comparison"]["schema_compatible"] is False
    assert report["comparison"]["different_schema_objects"] > 0
    assert "CREATE TABLE" not in repr(report)
    assert "private conversation" not in repr(report)

    sqlite_db.close()
    turso_db.close()
