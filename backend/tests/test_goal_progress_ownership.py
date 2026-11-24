"""Regression tests for ownership and strict typing of goal progress API."""
import asyncio
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server


@pytest.fixture
def goals_db(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            progress REAL NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE goal_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            evidence TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO goals(user_id,title) VALUES('alice','Objectif privé');
        INSERT INTO goal_steps(goal_id,status,evidence)
            VALUES(1,'completed','Preuve réelle');
        INSERT INTO goals(user_id,title) VALUES('creator','Objectif du créateur');
        INSERT INTO goal_steps(goal_id,status,evidence)
            VALUES(2,'completed','Preuve réelle');
    """)

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(server, "db_connection", connection)
    yield db
    db.close()


def test_goal_progress_api_rejects_another_users_goal_without_mutation(goals_db):
    request = server.GoalStepRequest(goal_id=1)
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.api_goal_progress(request, auth="creator"))
    assert error.value.status_code == 422
    row = goals_db.execute(
        "SELECT progress,status FROM goals WHERE id=1"
    ).fetchone()
    assert row["progress"] == 0
    assert row["status"] == "active"


def test_goal_progress_api_updates_only_authenticated_users_goal(goals_db):
    request = server.GoalStepRequest(goal_id=2)
    result = asyncio.run(server.api_goal_progress(request, auth="creator"))
    assert result["success"] is True
    assert result["result"]["progress"] == 100.0
    assert goals_db.execute(
        "SELECT progress FROM goals WHERE id=1"
    ).fetchone()["progress"] == 0


@pytest.mark.parametrize("bad_id", [True, False, 1.5, "1", 0, -1])
def test_goal_progress_request_rejects_non_strict_identifiers(bad_id):
    with pytest.raises(ValidationError):
        server.GoalStepRequest(goal_id=bad_id)


@pytest.mark.parametrize("bad_completed", [1, 0, "true", "false"])
def test_goal_progress_request_rejects_coerced_booleans(bad_completed):
    with pytest.raises(ValidationError):
        server.GoalStepRequest(goal_id=1, completed=bad_completed)


def test_empty_goal_progress_stays_zero_and_active(goals_db):
    goals_db.execute(
        "INSERT INTO goals(user_id,title) VALUES('creator','Sans étapes')"
    )
    goal_id = goals_db.execute(
        "SELECT id FROM goals WHERE title='Sans étapes'"
    ).fetchone()["id"]
    result = server.update_goal_progress(goals_db, "creator", goal_id)
    assert result["progress"] == 0.0
    assert result["status"] == "active"
