"""V50.34 — isolated continuity tests for the shared chat/Live persistence path.

These tests exercise the real persistence function with a temporary SQLite file.
They do not open a Gemini connection, contact Render/Turso, or touch production.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import server
from cognition.shared_brain import get_shared_brain_snapshot
from memory.autobiographical import init_autobiographical_tables
from learning.language import init_language_tables


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    db_path = tmp_path / "continuity.sqlite3"

    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_conversations_user_id
                ON conversations(user_id, id DESC);
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                entry TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        init_autobiographical_tables(db)
        init_language_tables(db)
        db.commit()

    @contextmanager
    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    monkeypatch.setattr(server, "db_connection", connect)
    monkeypatch.setattr(server, "valid_user", lambda user_id: user_id)
    return db_path, connect


def _snapshot(connect):
    with connect() as db:
        return get_shared_brain_snapshot(db, "creator", limit=20)


def test_chat_turn_is_visible_to_the_next_live_shared_brain_read(isolated_memory):
    _, connect = isolated_memory

    server.save_conversation_turn(
        "creator",
        "Je préfère le bleu.",
        "Je retiens que tu préfères le bleu.",
        source="conversation",
    )

    snapshot = _snapshot(connect)
    episodes = snapshot["autobiographical_events"]
    contents = {item["content"] for item in episodes}
    assert "Je préfère le bleu." in contents
    assert "Je retiens que tu préfères le bleu." in contents

    with connect() as db:
        source = db.execute(
            "SELECT kind FROM journal WHERE user_id='creator'"
        ).fetchone()["kind"]
    assert source == "conversation"


def test_live_turn_is_visible_to_the_next_chat_shared_brain_read(isolated_memory):
    _, connect = isolated_memory

    server.save_conversation_turn(
        "creator",
        "J'ai entendu le mot luciole.",
        "Luciole.",
        source="gemini_live",
    )

    snapshot = _snapshot(connect)
    episodes = snapshot["autobiographical_events"]
    contents = {item["content"] for item in episodes}
    assert "J'ai entendu le mot luciole." in contents
    assert "Luciole." in contents

    with connect() as db:
        source = db.execute(
            "SELECT kind FROM journal WHERE user_id='creator'"
        ).fetchone()["kind"]
    assert source == "gemini_live"


def test_chat_and_live_share_one_ordered_persistent_history(isolated_memory):
    _, connect = isolated_memory

    server.save_conversation_turn(
        "creator", "Premier message écrit.", "Réponse écrite.",
        source="conversation",
    )
    server.save_conversation_turn(
        "creator", "Deuxième message vocal.", "Réponse vocale.",
        source="gemini_live",
    )

    # Simulate a process restart: close every connection and reopen the file.
    snapshot = _snapshot(connect)
    contents = [item["content"] for item in snapshot["autobiographical_events"]]
    assert "Premier message écrit." in contents
    assert "Réponse écrite." in contents
    assert "Deuxième message vocal." in contents
    assert "Réponse vocale." in contents

    with connect() as db:
        rows = db.execute(
            "SELECT kind FROM journal WHERE user_id='creator' ORDER BY id"
        ).fetchall()
    assert [row["kind"] for row in rows] == ["conversation", "gemini_live"]


def test_empty_interrupted_turn_is_not_persisted(isolated_memory):
    _, connect = isolated_memory

    # The Live bridge must not call the writer for a turn that never completed.
    server.save_conversation_turn(
        "creator", "", "", source="gemini_live"
    )

    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id='creator'"
        ).fetchone()[0]
        journal_count = db.execute(
            "SELECT COUNT(*) FROM journal WHERE user_id='creator'"
        ).fetchone()[0]
    assert count == 0
    assert journal_count == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known V50.33 gap: save_conversation_turn has no stable turn ID; "
        "replaying a completed Live turn currently inserts duplicates."
    ),
)
def test_replaying_same_turn_is_idempotent_future_contract(isolated_memory):
    _, connect = isolated_memory

    for _ in range(2):
        server.save_conversation_turn(
            "creator", "Même tour.", "Même réponse.", source="gemini_live"
        )

    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE user_id='creator' AND content IN ('Même tour.', 'Même réponse.')"
        ).fetchone()[0]
    assert count == 2
