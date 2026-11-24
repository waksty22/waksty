import sqlite3

from memory.episodic_memory import (
    apply_memory_decay,
    init_memory_tables,
    save_episodic_memory,
)


def test_explicitly_confirmed_memories_are_protected_from_decay():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_memory_tables(db)

    save_episodic_memory(
        db, "creator", "Préférence confirmée", importance=5,
        source_type="confirmed", allow_confirmation=True,
    )
    save_episodic_memory(
        db, "creator", "Souvenir ordinaire", importance=5,
        source_type="taught",
    )
    db.execute(
        "UPDATE memories_v19 SET updated_at='2000-01-01T00:00:00+00:00', access_count=0"
    )
    db.commit()

    changed = apply_memory_decay(db, "creator", days=30)

    rows = {
        row["content"]: row["importance"]
        for row in db.execute("SELECT content, importance FROM memories_v19")
    }
    assert changed == 1
    assert rows["Préférence confirmée"] == 5
    assert rows["Souvenir ordinaire"] == 4
    db.close()
