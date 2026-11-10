import sqlite3

from storage.data_migration import build_data_migration_plan, migrate_sqlite_rows_to_turso


RECONCILABLE_TABLES = (
    "conversation_summaries",
    "dreams",
    "emotional_state",
    "goal_steps",
    "goals",
    "journal",
    "maintenance_state",
    "mood_events",
    "relationships",
    "voice_profiles",
)


def _open_pair():
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    source.execute("PRAGMA foreign_keys=ON")
    target.execute("PRAGMA foreign_keys=ON")
    return source, target


def test_allowlisted_legacy_tables_rebuild_on_check_drift_and_preserve_rows():
    source, target = _open_pair()
    try:
        for table in RECONCILABLE_TABLES:
            source.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, label TEXT NOT NULL "
                "CHECK(label IN ('a','b')))"
            )
            target.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, label TEXT NOT NULL "
                "CHECK(label IN ('a','b','legacy')))"
            )
            source.execute(f"INSERT INTO {table} VALUES (1, 'a')")
            source.execute(f"INSERT INTO {table} VALUES (2, 'b')")
            target.execute(f"INSERT INTO {table} VALUES (1, 'a')")

        source.commit()
        target.commit()
        plan = build_data_migration_plan(source, target)

        assert plan["ready"] is True, plan["blockers"]
        rebuilds = {
            item["object"]
            for item in plan["schema_plan"]["statements"]
            if item["kind"] == "rebuild_table"
        }
        assert set(RECONCILABLE_TABLES).issubset(rebuilds)

        result = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert result["applied"] is True
        for table in RECONCILABLE_TABLES:
            assert target.execute(
                f"SELECT label FROM {table} ORDER BY id"
            ).fetchall() == [("a",), ("b",)]
    finally:
        source.close()
        target.close()


def test_allowlisted_default_drift_rebuilds_without_overwriting_existing_values():
    source, target = _open_pair()
    try:
        source.execute(
            "CREATE TABLE journal (id INTEGER PRIMARY KEY, "
            "entry TEXT NOT NULL DEFAULT 'canonical')"
        )
        target.execute(
            "CREATE TABLE journal (id INTEGER PRIMARY KEY, "
            "entry TEXT NOT NULL DEFAULT 'legacy')"
        )
        source.execute("INSERT INTO journal(id, entry) VALUES (1, 'source-row')")
        target.execute("INSERT INTO journal(id, entry) VALUES (2, 'target-row')")
        source.commit()
        target.commit()

        plan = build_data_migration_plan(source, target)
        assert plan["ready"] is True, plan["blockers"]
        assert any(
            item.get("kind") == "rebuild_table" and item.get("object") == "journal"
            for item in plan["schema_plan"]["statements"]
        )

        result = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert result["applied"] is True
        assert target.execute(
            "SELECT id, entry FROM journal ORDER BY id"
        ).fetchall() == [(1, "source-row"), (2, "target-row")]
        target.execute("INSERT INTO journal(id) VALUES (3)")
        assert target.execute(
            "SELECT entry FROM journal WHERE id=3"
        ).fetchone()[0] == "canonical"
    finally:
        source.close()
        target.close()


def test_unsafe_column_type_drift_remains_blocked_without_writes():
    source, target = _open_pair()
    try:
        source.execute(
            "CREATE TABLE relationships (id INTEGER PRIMARY KEY, trust REAL NOT NULL)"
        )
        target.execute(
            "CREATE TABLE relationships (id INTEGER PRIMARY KEY, trust TEXT NOT NULL)"
        )
        target.execute("INSERT INTO relationships VALUES (1, 'unverified')")
        source.commit()
        target.commit()

        plan = build_data_migration_plan(source, target)
        assert plan["ready"] is False
        assert target.execute(
            "SELECT trust FROM relationships WHERE id=1"
        ).fetchone()[0] == "unverified"
    finally:
        source.close()
        target.close()



def test_all_missing_learning_tables_are_planned_and_created_empty():
    source, target = _open_pair()
    missing = (
        "affective_history", "autobiographical_events", "autobiographical_links",
        "causal_experiments", "causal_hypotheses", "causal_observations",
        "cognitive_milestones", "cognitive_traces", "competency_tests",
        "decision_journal", "imitation_attempts", "imitation_examples",
        "memories_v19", "metacognition_logs", "object_experiences",
        "object_properties", "perception_fusion_candidates", "personal_vocabulary",
        "place_memories", "preference_evidence", "sensory_observations",
        "spatial_sessions", "spatial_visits", "thoughts", "user_intentions",
        "word_visual_associations", "world_entities", "world_relations",
    )
    try:
        for table in missing:
            source.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
        source.commit()
        target.commit()

        plan = build_data_migration_plan(source, target)
        assert plan["ready"] is True, plan["blockers"]
        assert set(plan["schema_plan"]["missing_tables"]) == set(missing)
        create_tables = {
            item["object"] for item in plan["schema_plan"]["statements"]
            if item["kind"] == "create_table"
        }
        assert create_tables == set(missing)

        result = migrate_sqlite_rows_to_turso(source, target, apply=True)
        assert result["applied"] is True
        for table in missing:
            assert target.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0] == 1
            assert target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        source.close()
        target.close()
