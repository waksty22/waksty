import sqlite3

from storage.schema_audit import inspect_database, compare_database_inventories


def _database(sql: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(sql)
    return connection


def test_inspect_database_reports_generated_columns_and_extended_index_metadata():
    connection = _database(
        """
        CREATE TABLE sample (
            id INTEGER PRIMARY KEY,
            raw TEXT NOT NULL,
            normalized TEXT GENERATED ALWAYS AS (lower(raw)) STORED
        );
        CREATE INDEX idx_sample_raw
            ON sample(raw COLLATE NOCASE DESC);
        """
    )
    try:
        inventory = inspect_database(connection)
        assert inventory["metadata_capabilities"]["table_xinfo_supported"] is True
        assert inventory["metadata_capabilities"]["index_xinfo_supported"] is True

        columns = inventory["tables"]["sample"]["columns"]
        generated = next(column for column in columns if column["name"] == "normalized")
        assert generated["generated_or_hidden"] is True
        assert generated["hidden"] in (2, 3)
        assert generated["metadata_complete"] is True

        index = next(
            item for item in inventory["tables"]["sample"]["indexes"]
            if item["name"] == "idx_sample_raw"
        )
        key_column = next(column for column in index["columns"] if column["key_column"])
        assert key_column["collation"].lower() == "nocase"
        assert key_column["descending"] is True
        assert index["metadata_complete"] is True
    finally:
        connection.close()


def test_compare_database_inventories_marks_missing_unique_index_as_blocking():
    local_connection = _database(
        """
        CREATE TABLE sample (id INTEGER PRIMARY KEY, external_id TEXT);
        CREATE UNIQUE INDEX uq_sample_external_id ON sample(external_id);
        """
    )
    remote_connection = _database(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY, external_id TEXT);"
    )
    try:
        local = inspect_database(local_connection)
        remote = inspect_database(remote_connection)
        comparison = compare_database_inventories(local, remote)
        audit = comparison["detailed_audit"]

        assert audit["schema_readiness"] == "blocked"
        assert audit["migration_readiness"] == "not_assessed"
        assert audit["migration_blocked_by_schema"] is True
        assert any(
            item["category"] == "missing_unique_constraint"
            and item["severity"] == "blocking"
            for item in audit["differences"]
        )
    finally:
        local_connection.close()
        remote_connection.close()


def test_schema_audit_does_not_modify_database_rows():
    connection = _database(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT);"
    )
    connection.execute("INSERT INTO sample(value) VALUES ('keep')")
    connection.commit()
    try:
        before = connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
        inspect_database(connection)
        after = connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
        assert before == after == 1
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "keep"
    finally:
        connection.close()
