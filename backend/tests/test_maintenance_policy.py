import sqlite3

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
