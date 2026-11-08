"""Regression test: additive schema changes preserve all pre-existing target rows."""
import sqlite3

from storage.schema_migration import build_migration_plan, apply_migration_plan


def test_five_existing_turso_rows_survive_additive_schema_upgrade():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    try:
        source.executescript("""
            CREATE TABLE emotional_state(id INTEGER PRIMARY KEY, mood TEXT NOT NULL);
            CREATE TABLE journal(id INTEGER PRIMARY KEY, entry TEXT NOT NULL);
            CREATE TABLE maintenance_state(id INTEGER PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE relationships(id INTEGER PRIMARY KEY, relation TEXT NOT NULL);
            CREATE TABLE voice_profiles(id INTEGER PRIMARY KEY, profile TEXT NOT NULL);
            CREATE TABLE conversations(id INTEGER PRIMARY KEY, message TEXT NOT NULL);
            CREATE INDEX idx_conversations_id ON conversations(id);
        """)
        target.executescript("""
            CREATE TABLE emotional_state(id INTEGER PRIMARY KEY, mood TEXT NOT NULL);
            CREATE TABLE journal(id INTEGER PRIMARY KEY, entry TEXT NOT NULL);
            CREATE TABLE maintenance_state(id INTEGER PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE relationships(id INTEGER PRIMARY KEY, relation TEXT NOT NULL);
            CREATE TABLE voice_profiles(id INTEGER PRIMARY KEY, profile TEXT NOT NULL);
            INSERT INTO emotional_state VALUES (1, 'calm');
            INSERT INTO journal VALUES (1, 'existing journal row');
            INSERT INTO maintenance_state VALUES (1, 'healthy');
            INSERT INTO relationships VALUES (1, 'creator');
            INSERT INTO voice_profiles VALUES (1, 'default');
        """)
        before = {
            table: target.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "emotional_state", "journal", "maintenance_state",
                "relationships", "voice_profiles"
            )
        }

        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        assert "conversations" in plan["missing_tables"]

        result = apply_migration_plan(target, plan, apply=True)
        assert result["applied"] is True
        after = {
            table: target.execute(f"SELECT * FROM {table}").fetchall()
            for table in before
        }
        assert after == before
        assert sum(len(rows) for rows in after.values()) == 5
        assert target.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
    finally:
        source.close()
        target.close()
