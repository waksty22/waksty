import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition import maintenance


def test_passive_maintenance_does_not_drain_energy_or_increase_sadness(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.execute(
        """CREATE TABLE emotional_state (
            user_id TEXT PRIMARY KEY,
            energy REAL NOT NULL,
            sadness REAL NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE journal (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            entry TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO emotional_state VALUES (?, ?, ?, ?)",
        ("creator", 73.0, 12.0, "2026-11-18T12:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO journal(user_id, entry, kind, created_at) VALUES (?, ?, ?, ?)",
        ("creator", "Entrée existante", "thought", "2026-11-18T12:00:00+00:00"),
    )
    db.commit()

    monkeypatch.setattr(maintenance, "apply_memory_decay", lambda _db, _uid: None)
    maintenance.apply_passive_maintenance(db, "creator")

    state = db.execute(
        "SELECT energy, sadness FROM emotional_state WHERE user_id='creator'"
    ).fetchone()
    journal_count = db.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    assert state == (73.0, 12.0)
    assert journal_count == 1
    db.close()


def test_maintenance_runs_due_work_on_process_startup(monkeypatch, tmp_path):
    import asyncio
    from datetime import datetime, timedelta, timezone
    import sqlite3

    import server

    database_path = tmp_path / "maintenance-startup.sqlite3"
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=9)).isoformat()
    recent = now.isoformat()

    def connect():
        db = sqlite3.connect(database_path)
        db.row_factory = sqlite3.Row
        db.execute(
            """CREATE TABLE IF NOT EXISTS maintenance_state (
                user_id TEXT PRIMARY KEY,
                last_active_at TEXT NOT NULL,
                last_dream_at TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS thoughts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        return db

    setup = connect()
    setup.execute(
        "INSERT INTO maintenance_state VALUES (?, ?, ?, ?)",
        ("creator", old, old, recent),
    )
    setup.execute(
        "INSERT INTO thoughts(user_id, content, created_at) VALUES (?, ?, ?)",
        ("creator", "Pensée récente", recent),
    )
    setup.commit()
    setup.close()

    monkeypatch.setattr(server, "db_connection", connect)
    monkeypatch.setattr(server, "apply_passive_maintenance", lambda _db, _uid: None)
    dreams = []
    monkeypatch.setattr(server, "generate_dream", lambda uid: dreams.append(uid))
    monkeypatch.setattr(server, "generate_rumination", lambda _uid: None)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)

    async def stop_at_first_wait(_seconds):
        # Reaching the first wait proves the initial maintenance pass ran.
        raise asyncio.CancelledError

    monkeypatch.setattr(server.asyncio, "sleep", stop_at_first_wait)

    async def run_once():
        try:
            await server.autonomous_maintenance_loop()
        except asyncio.CancelledError:
            pass

    asyncio.run(run_once())
    assert dreams == ["creator"]


def test_dream_api_calls_synchronous_generator_without_await(monkeypatch):
    import asyncio
    import server

    monkeypatch.setattr(
        server, "generate_dream",
        lambda user_id: {"dream": f"Rêve de {user_id}", "simulated": True},
    )

    response = asyncio.run(server.api_generate_dream(None, auth="creator"))
    assert response == {
        "success": True,
        "dream": {"dream": "Rêve de creator", "simulated": True},
    }


def test_memory_reflection_label_preserves_epistemic_provenance():
    import server

    assert server._memory_reflection_label({"source_type": "taught"}) == (
        "un souvenir appris ou confirmé"
    )
    assert server._memory_reflection_label({"source_type": "confirmed"}) == (
        "un souvenir appris ou confirmé"
    )
    assert server._memory_reflection_label({"source_type": "observed"}) == (
        "une observation enregistrée"
    )
    assert server._memory_reflection_label({"source_type": "inferred"}) == (
        "une piste non vérifiée"
    )
    assert server._memory_reflection_label({"source_type": "unknown"}) == (
        "un élément dont la provenance est inconnue"
    )
    assert server._memory_reflection_label(None) == (
        "une idée sans souvenir enregistré"
    )
