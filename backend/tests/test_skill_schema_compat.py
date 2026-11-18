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


def test_get_emotions_supports_existing_skills_schema_without_xp(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "chappie.sqlite3"
    _prepare_legacy_skills_database(database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(server, "DB_PATH", database_path)

    emotions = server.get_emotions("creator")

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
