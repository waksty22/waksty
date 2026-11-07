"""V50 schema parity and isolated SQLite-to-libSQL migration dry run."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import libsql

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from storage.libsql_adapter import adapt_libsql_connection
from storage.schema_audit import (\n    compare_schemas, inspect_schema, inspect_database,\n    compare_database_inventories,\n)
from memory.episodic_memory import init_memory_tables
from memory.autobiographical import init_autobiographical_tables
from world.spatial_memory import init_spatial_tables
from world.world_model import init_world_tables
from learning.curriculum import init_learning_tables
from learning.language import init_language_tables
from learning.sensory import init_sensory_tables
from learning.object_learning import init_object_learning_tables
from learning.causal_learning import init_causal_learning_tables
from learning.supervised_learning import init_supervised_learning_tables
from learning.perception_fusion import init_perception_fusion_tables
from cognition.reasoning import init_cognition_tables
from cognition.development import init_development_tables


INITIALIZERS = (
    init_memory_tables,
    init_autobiographical_tables,
    init_spatial_tables,
    init_world_tables,
    init_learning_tables,
    init_language_tables,
    init_sensory_tables,
    init_object_learning_tables,
    init_causal_learning_tables,
    init_supervised_learning_tables,
    init_perception_fusion_tables,
    init_cognition_tables,
    init_development_tables,
)


def test_thirteen_subsystem_schemas_match_between_sqlite_and_libsql():
    sqlite_db = sqlite3.connect(":memory:")
    libsql_native = libsql.connect(database=":memory:")
    libsql_db = adapt_libsql_connection(libsql_native)
    try:
        for initialize in INITIALIZERS:
            initialize(sqlite_db)
            initialize(libsql_db)

        report = compare_schemas(
            inspect_schema(sqlite_db),
            inspect_schema(libsql_db),
        )
        assert report["compatible"], report
        assert report["left_table_count"] >= 13
        assert report["left_object_count"] >= report["left_table_count"]
    finally:
        sqlite_db.close()
        libsql_db.close()


def _make_source_database(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE people (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                profile BLOB
            );
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY,
                person_id INTEGER NOT NULL REFERENCES people(id),
                content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5
            );
            CREATE INDEX idx_memories_person ON memories(person_id);
            CREATE VIEW memory_counts AS
                SELECT person_id, COUNT(*) AS total
                FROM memories GROUP BY person_id;
            CREATE TABLE migration_audit (
                id INTEGER PRIMARY KEY,
                event TEXT NOT NULL
            );
            CREATE TRIGGER memories_insert_audit
            AFTER INSERT ON memories
            BEGIN
                INSERT INTO migration_audit(event)
                VALUES ('memory_inserted');
            END;
            INSERT INTO people(id, name, profile)
                VALUES (7, 'synthetic-user', X'010203');
            INSERT INTO memories(id, person_id, content, confidence)
                VALUES (11, 7, 'synthetic-memory', 0.9);
            """
        )
        db.commit()
    finally:
        db.close()


def _copy_fixture_to_empty_target(source: sqlite3.Connection, target) -> None:
    existing = target.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if existing:
        raise ValueError("La cible de migration doit être vide.")

    source_objects = source.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
          AND sql IS NOT NULL
        ORDER BY CASE type
            WHEN 'table' THEN 0
            WHEN 'index' THEN 1
            WHEN 'trigger' THEN 2
            WHEN 'view' THEN 3
            ELSE 4 END, name
        """
    ).fetchall()

    tables = [row for row in source_objects if row[0] == "table"]
    deferred = [row for row in source_objects if row[0] != "table"]

    target.execute("PRAGMA foreign_keys=OFF")
    try:
        for _kind, _name, create_sql in tables:
            target.execute(create_sql)

        for _kind, table_name, _create_sql in tables:
            columns = [
                row[1] for row in source.execute(
                    f'PRAGMA table_info("{table_name.replace(chr(34), chr(34)*2)}")'
                ).fetchall()
            ]
            if not columns:
                continue
            quoted_columns = ", ".join(
                '"' + column.replace('"', '""') + '"' for column in columns
            )
            rows = source.execute(
                f'SELECT {quoted_columns} FROM "{table_name.replace(chr(34), chr(34)*2)}"'
            ).fetchall()
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                target.executemany(
                    f'INSERT INTO "{table_name.replace(chr(34), chr(34)*2)}" '
                    f"({quoted_columns}) VALUES ({placeholders})",
                    rows,
                )

        for _kind, _name, create_sql in deferred:
            target.execute(create_sql)
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        target.execute("PRAGMA foreign_keys=ON")


def test_isolated_migration_dry_run_preserves_schema_data_and_relations(tmp_path):
    source_path = tmp_path / "synthetic-source.sqlite3"
    _make_source_database(source_path)
    source = sqlite3.connect(source_path)
    target_native = libsql.connect(database=":memory:")
    target = adapt_libsql_connection(target_native)
    try:
        _copy_fixture_to_empty_target(source, target)

        schema_report = compare_schemas(
            inspect_schema(source),
            inspect_schema(target),
        )
        assert schema_report["compatible"], schema_report

        people = target.execute(
            "SELECT id, name, profile FROM people WHERE id=7"
        ).fetchone()
        assert people[0] == 7
        assert people[1] == "synthetic-user"
        assert bytes(people[2]) == b"\x01\x02\x03"

        memory = target.execute(
            "SELECT person_id, content, confidence FROM memories WHERE id=11"
        ).fetchone()
        assert tuple(memory) == (7, "synthetic-memory", 0.9)
        assert target.execute(
            "SELECT total FROM memory_counts WHERE person_id=7"
        ).fetchone()[0] == 1

        # The source fixture's initial insert already fired the trigger once.
        assert target.execute(
            "SELECT COUNT(*) FROM migration_audit"
        ).fetchone()[0] == 1
        target.execute(
            "INSERT INTO memories(id, person_id, content) VALUES (12, 7, 'second')"
        )
        assert target.execute(
            "SELECT COUNT(*) FROM migration_audit"
        ).fetchone()[0] == 2
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        source.close()
        target.close()



def test_read_only_inventory_reports_counts_and_schema_differences(tmp_path):
    source_path = tmp_path / "inventory-source.sqlite3"
    _make_source_database(source_path)
    source = sqlite3.connect(source_path)
    target_native = libsql.connect(database=":memory:")
    target = adapt_libsql_connection(target_native)
    try:
        _copy_fixture_to_empty_target(source, target)
        source_inventory = inspect_database(source)
        target_inventory = inspect_database(target)

        assert source_inventory["table_count"] == 3
        assert source_inventory["total_rows"] == 3
        assert source_inventory["foreign_key_violations"] == 0
        assert source_inventory["tables"]["memories"]["row_count"] == 1
        assert source_inventory["tables"]["memories"]["foreign_keys"][0][
            "referenced_table"
        ] == "people"

        comparison = compare_database_inventories(
            source_inventory,
            target_inventory,
        )
        assert comparison["compatible"], comparison
        assert comparison["row_count_differences"] == {}
    finally:
        source.close()
        target.close()
