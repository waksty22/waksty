from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


def _prepare_legacy_skills_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE emotional_state (
                user_id TEXT PRIMARY KEY,
                joy REAL NOT NULL,
                fear REAL NOT NULL,
                curiosity REAL NOT NULL,
                frustration REAL NOT NULL,
                sadness REAL NOT NULL,
                energy REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE relationships (
                user_id TEXT PRIMARY KEY,
                trust REAL NOT NULL,
                affection REAL NOT NULL,
                dependence REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE user_intentions (
                user_id TEXT PRIMARY KEY,
                current_intent TEXT NOT NULL,
                confidence REAL NOT NULL,
                details TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE maintenance_state (
                user_id TEXT PRIMARY KEY,
                last_active_at TEXT NOT NULL,
                last_dream_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                level REAL NOT NULL DEFAULT 0.0,
                evidence TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, skill_name)
            );
            CREATE TABLE competency_tests (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                test_name TEXT NOT NULL,
                passed INTEGER NOT NULL,
                score REAL NOT NULL,
                details TEXT NOT NULL,
                tested_at TEXT NOT NULL
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_explicit_initialization_supports_existing_skills_schema_without_xp(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "chappie.sqlite3"
    _prepare_legacy_skills_database(database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "DB_PATH", database_path)

    emotions = server.get_emotions("creator")
    server.ensure_user_state_initialized("creator")

    assert emotions["user_id"] == "creator"
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(skills)")
        }
        skill_count = connection.execute(
            "SELECT COUNT(*) FROM skills WHERE user_id=?", ("creator",)
        ).fetchone()[0]

    assert "xp" not in columns
    assert skill_count == 6


def test_get_skills_summary_exposes_legacy_xp_as_zero_without_schema_change(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "chappie.sqlite3"
    _prepare_legacy_skills_database(database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "DB_PATH", database_path)

    summary = server.get_skills_summary("creator")

    assert len(summary["skills"]) == 6
    assert all(skill["xp"] == 0.0 for skill in summary["skills"])
    assert summary["legacy_aggregate_xp_affects_maturity"] is False
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(skills)")
        }
    assert "xp" not in columns


def test_emotion_and_relationship_getters_are_read_only(monkeypatch, tmp_path):
    database_path = tmp_path / "read-only.sqlite3"
    _prepare_legacy_skills_database(database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "DB_PATH", database_path)

    emotions = server.get_emotions("creator")
    relationship = server.get_relationship("creator")
    intention = server.get_user_intention("creator")

    assert emotions["energy"] == 100.0
    assert relationship["trust"] == 50.0
    assert intention["current_intent"] == "discussion libre"
    with sqlite3.connect(database_path) as connection:
        for table in (
            "emotional_state", "relationships", "user_intentions",
            "skills", "maintenance_state",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                ("creator",),
            ).fetchone()[0]
            assert count == 0, f"{table} was unexpectedly initialized by a getter"


def test_state_initialization_is_explicit_idempotent_and_preserves_progress(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "explicit-init.sqlite3"
    _prepare_legacy_skills_database(database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "DB_PATH", database_path)

    server.ensure_user_state_initialized("creator")
    from contextlib import contextmanager

    original_db_connection = server.db_connection
    write_deltas = []

    @contextmanager
    def tracked_db_connection():
        with original_db_connection() as db:
            before = db.total_changes
            yield db
            write_deltas.append(db.total_changes - before)

    monkeypatch.setattr(server, "db_connection", tracked_db_connection)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE emotional_state SET joy=42 WHERE user_id='creator'"
        )
        connection.execute(
            "UPDATE relationships SET trust=73 WHERE user_id='creator'"
        )
        connection.commit()

    server.ensure_user_state_initialized("creator")
    assert write_deltas[-1] == 0, "repeat initialization must not write rows"
    with sqlite3.connect(database_path) as connection:
        joy = connection.execute(
            "SELECT joy FROM emotional_state WHERE user_id='creator'"
        ).fetchone()[0]
        trust = connection.execute(
            "SELECT trust FROM relationships WHERE user_id='creator'"
        ).fetchone()[0]
        skill_count = connection.execute(
            "SELECT COUNT(*) FROM skills WHERE user_id='creator'"
        ).fetchone()[0]

    assert joy == 42
    assert trust == 73
    assert skill_count == 6
