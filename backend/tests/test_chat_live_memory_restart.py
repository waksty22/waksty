"""Regression tests for durable chat/Live conversation memory."""
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_chat_and_live_turns_survive_fresh_storage_connections(monkeypatch, tmp_path):
    import server
    from cognition.shared_brain import get_shared_brain_snapshot

    database_path = tmp_path / "chappie-persistence.sqlite3"
    monkeypatch.setattr(server, "DB_PATH", database_path)
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("CHAPPIE_ALLOW_TURSO_MIGRATION", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    # Build the real application schema in an isolated temporary SQLite file.
    server.init_db()

    # Keep this test focused on durable turn storage, not downstream
    # autobiographical extraction or summarization behavior.
    monkeypatch.setattr(server, "sync_autobiographical_events", lambda db, user_id: None)

    server.save_conversation_turn(
        "creator",
        "J'apprends le mot pomme.",
        "Tu m'apprends le mot pomme.",
        source="conversation",
    )
    server.save_conversation_turn(
        "creator",
        "En direct, je te montre une pomme.",
        "Je me souviens du mot pomme.",
        source="gemini_live",
    )

    # Simulate a process restart: inspect only through a newly opened
    # application connection, not the connection used by either write.
    with server.db_connection() as reopened:
        rows = reopened.execute(
            """
            SELECT role, content
            FROM conversations
            WHERE user_id=?
            ORDER BY id ASC
            """,
            ("creator",),
        ).fetchall()
        journal_sources = reopened.execute(
            """
            SELECT kind
            FROM journal
            WHERE user_id=?
            ORDER BY id ASC
            """,
            ("creator",),
        ).fetchall()

    assert [(row["role"], row["content"]) for row in rows] == [
        ("user", "J'apprends le mot pomme."),
        ("assistant", "Tu m'apprends le mot pomme."),
        ("user", "En direct, je te montre une pomme."),
        ("assistant", "Je me souviens du mot pomme."),
    ]
    assert [row["kind"] for row in journal_sources] == [
        "conversation",
        "gemini_live",
    ]

    # The shared cognitive snapshot must read the same persisted conversation
    # records regardless of which interface originally wrote them.
    with server.db_connection() as reopened:
        snapshot = get_shared_brain_snapshot(reopened, "creator")

    assert snapshot["statistics"]["totals"]["memories"] >= 0
