import sqlite3

import pytest

from storage.schema_migration import apply_migration_plan, build_migration_plan


def _conversation_pair(*, target_has_invalid_role=False, inbound_fk=False):
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_conversations_user_id
            ON conversations(user_id, id DESC);
        INSERT INTO conversations(user_id, role, content, created_at)
        VALUES ('creator', 'user', 'hello', '2026-01-01');
    """)
    target.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_conversations_user_id
            ON conversations(user_id);
    """)
    role = "system" if target_has_invalid_role else "assistant"
    target.execute(
        "INSERT INTO conversations(user_id, role, content, created_at) "
        "VALUES ('creator', ?, 'existing', '2026-01-02')",
        (role,),
    )
    if inbound_fk:
        source.execute("""
            CREATE TABLE conversation_refs (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(id)
            )
        """)
        target.execute("""
            CREATE TABLE conversation_refs (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(id)
            )
        """)
        target.execute(
            "INSERT INTO conversation_refs(id, conversation_id) VALUES (1, 1)"
        )
    source.commit()
    target.commit()
    return source, target


def test_check_constraint_rebuild_preserves_rows_and_indexes():
    source, target = _conversation_pair()
    try:
        before = target.execute(
            "SELECT id, user_id, role, content, created_at FROM conversations ORDER BY id"
        ).fetchall()
        plan = build_migration_plan(source, target)

        assert plan["ready"], plan["blockers"]
        rebuilds = [
            item for item in plan["statements"]
            if item["kind"] == "rebuild_table" and item["object"] == "conversations"
        ]
        assert len(rebuilds) == 1
        assert apply_migration_plan(target, plan)["applied"] is False

        result = apply_migration_plan(target, plan, apply=True)
        assert result["applied"] is True
        assert target.execute(
            "SELECT id, user_id, role, content, created_at FROM conversations ORDER BY id"
        ).fetchall() == before

        create_sql = target.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='conversations'"
        ).fetchone()[0]
        assert "'system'" not in create_sql
        index_columns = target.execute(
            "PRAGMA index_info(idx_conversations_user_id)"
        ).fetchall()
        assert [row[2] for row in index_columns] == ["user_id", "id"]

        second = build_migration_plan(source, target)
        assert second["ready"], second["blockers"]
        assert second["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()


def test_rebuild_aborts_and_rolls_back_if_existing_row_violates_source_check():
    source, target = _conversation_pair(target_has_invalid_role=True)
    try:
        before = target.execute(
            "SELECT id, user_id, role, content, created_at FROM conversations"
        ).fetchall()
        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]

        with pytest.raises(sqlite3.IntegrityError):
            apply_migration_plan(target, plan, apply=True)

        after = target.execute(
            "SELECT id, user_id, role, content, created_at FROM conversations"
        ).fetchall()
        assert after == before
        assert target.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='__chappie_rebuild_conversations'"
        ).fetchone()[0] == 0
    finally:
        source.close()
        target.close()


def test_rebuild_is_blocked_when_another_table_references_target():
    source, target = _conversation_pair(inbound_fk=True)
    try:
        plan = build_migration_plan(source, target)
        assert not plan["ready"]
        assert any("référencée par une clé étrangère" in item for item in plan["blockers"])
    finally:
        source.close()
        target.close()


def test_memories_check_and_skills_level_drift_are_rebuilt_safely():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
            tags TEXT NOT NULL DEFAULT '[]',
            access_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        );
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0.0,
            xp REAL NOT NULL DEFAULT 0.0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, skill_name)
        );
        INSERT INTO memories(user_id, category, content, importance, created_at, updated_at)
        VALUES ('creator', 'fact', 'kept', 4, 'now', 'now');
        INSERT INTO skills(user_id, skill_name, level, updated_at)
        VALUES ('creator', 'language', 1.5, 'now');
    """)
    target.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER NOT NULL CHECK(importance BETWEEN 0 AND 10),
            tags TEXT NOT NULL DEFAULT '[]',
            access_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, content)
        );
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 0,
            xp REAL NOT NULL DEFAULT 0.0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, skill_name)
        );
        INSERT INTO memories(user_id, category, content, importance, created_at, updated_at)
        VALUES ('creator', 'fact', 'existing-memory', 4, 'before', 'before');
        INSERT INTO skills(user_id, skill_name, level, updated_at)
        VALUES ('creator', 'existing-skill', 2, 'before');
    """)
    source.commit()
    target.commit()
    try:
        before_memories = target.execute(
            "SELECT id, user_id, category, content, importance, tags, access_count, created_at, updated_at FROM memories"
        ).fetchall()
        before_skills = target.execute(
            "SELECT id, user_id, skill_name, level, xp, evidence, updated_at FROM skills"
        ).fetchall()
        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        assert {
            item["object"] for item in plan["statements"]
            if item["kind"] == "rebuild_table"
        } == {"memories", "skills"}

        apply_migration_plan(target, plan, apply=True)
        assert target.execute(
            "SELECT id, user_id, category, content, importance, tags, access_count, created_at, updated_at FROM memories"
        ).fetchall() == before_memories
        after_skills = target.execute(
            "SELECT id, user_id, skill_name, level, xp, evidence, updated_at FROM skills"
        ).fetchall()
        assert after_skills[0][:3] == before_skills[0][:3]
        assert float(after_skills[0][3]) == float(before_skills[0][3])
        assert after_skills[0][4:] == before_skills[0][4:]
        assert isinstance(after_skills[0][3], float)

        second = build_migration_plan(source, target)
        assert second["ready"], second["blockers"]
        assert second["planned_statement_count"] == 0
    finally:
        source.close()
        target.close()


def test_rebuild_refuses_tables_without_stable_primary_key():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("""
        CREATE TABLE conversations (
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE conversations (
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL
        )
    """)
    try:
        plan = build_migration_plan(source, target)
        assert not plan["ready"]
        assert any("clé primaire stable" in item for item in plan["blockers"])
    finally:
        source.close()
        target.close()



def test_sqlite_to_turso_flow_uses_verified_rebuild_before_copying_source_rows():
    from storage.data_migration import migrate_sqlite_rows_to_turso

    source, target = _conversation_pair()
    try:
        source.execute("DELETE FROM conversations WHERE id=1")
        source.execute(
            "INSERT INTO conversations(id, user_id, role, content, created_at) "
            "VALUES (2, 'creator', 'user', 'from-source', '2026-01-03')"
        )
        target.execute(
            "INSERT INTO conversations(id, user_id, role, content, created_at) "
            "VALUES (5, 'creator', 'assistant', 'target-kept', '2026-01-04')"
        )
        source.commit()
        target.commit()

        preview = migrate_sqlite_rows_to_turso(source, target)
        assert preview["applied"] is False
        assert preview["ready"] is True

        result = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert result["applied"] is True
        rows = target.execute(
            "SELECT id, content FROM conversations ORDER BY id"
        ).fetchall()
        assert rows == [(1, "existing"), (2, "from-source"), (5, "target-kept")]
    finally:
        source.close()
        target.close()



def test_rebuild_runs_on_the_libsql_compatibility_adapter():
    import libsql
    from storage.libsql_adapter import adapt_libsql_connection

    source = sqlite3.connect(":memory:")
    native = libsql.connect(database=":memory:")
    target = adapt_libsql_connection(native)
    source.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    target.execute(
        "INSERT INTO conversations(user_id, role, content, created_at) "
        "VALUES ('creator', 'assistant', 'keep-on-libsql', 'now')"
    )
    target.commit()
    try:
        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        result = apply_migration_plan(target, plan, apply=True)
        assert result["applied"] is True
        row = target.execute(
            "SELECT content FROM conversations WHERE user_id='creator'"
        ).fetchone()
        assert row[0] == "keep-on-libsql"
    finally:
        source.close()
        target.close()


def test_rebuild_refuses_unreviewed_table_options():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT COLLATE NOCASE NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    target.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    try:
        plan = build_migration_plan(source, target)
        assert not plan["ready"]
        assert any("option ou clause SQL avancée" in item for item in plan["blockers"])
    finally:
        source.close()
        target.close()



def test_source_only_inbound_fk_is_created_before_parent_rebuild():
    source, target = _conversation_pair()
    source.execute("""
        CREATE TABLE autobiographical_events (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id)
        )
    """)
    source.execute(
        "INSERT INTO autobiographical_events(id, conversation_id) VALUES (1, 1)"
    )
    source.commit()
    try:
        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        kinds = [(item["kind"], item["object"]) for item in plan["statements"]]
        assert kinds.index(("create_table", "autobiographical_events")) < kinds.index(
            ("rebuild_table", "conversations")
        )

        applied = apply_migration_plan(target, plan, apply=True)
        assert applied["applied"] is True
        assert target.execute(
            "SELECT COUNT(*) FROM autobiographical_events"
        ).fetchone()[0] == 0
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        source.close()
        target.close()


def test_skills_rebuild_adds_allowlisted_missing_xp_and_preserves_existing_values():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.executescript("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level REAL NOT NULL DEFAULT 0.0,
            xp REAL NOT NULL DEFAULT 0.0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, skill_name)
        );
    """)
    target.executescript("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_name TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 0,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, skill_name)
        );
        INSERT INTO skills(user_id, skill_name, level, evidence, updated_at)
        VALUES ('creator', 'language', 2, 'kept', 'before');
    """)
    source.commit()
    target.commit()
    try:
        before = target.execute(
            "SELECT id, user_id, skill_name, level, evidence, updated_at FROM skills"
        ).fetchall()
        plan = build_migration_plan(source, target)
        assert plan["ready"], plan["blockers"]
        assert any(
            item["kind"] == "rebuild_table" and item["object"] == "skills"
            for item in plan["statements"]
        )

        result = apply_migration_plan(target, plan, apply=True)
        assert result["applied"] is True
        after = target.execute(
            "SELECT id, user_id, skill_name, level, evidence, updated_at FROM skills"
        ).fetchall()
        assert after == before
        assert target.execute(
            "SELECT xp FROM skills WHERE user_id='creator' AND skill_name='language'"
        ).fetchone()[0] == 0.0
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []

        second = build_migration_plan(source, target)
        assert second["ready"], second["blockers"]
    finally:
        source.close()
        target.close()
