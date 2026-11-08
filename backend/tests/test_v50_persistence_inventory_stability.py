from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.inspect_persistence_inventory import inspect_sqlite_database


def test_table_fingerprint_is_independent_of_row_insertion_order(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.sqlite3"
    second_path = tmp_path / "second.sqlite3"

    for path, values in (
        (first_path, [("alpha", 1), ("beta", 2), ("gamma", 3)]),
        (second_path, [("gamma", 3), ("alpha", 1), ("beta", 2)]),
    ):
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE facts (label TEXT NOT NULL, amount INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO facts(label, amount) VALUES (?, ?)", values
        )
        connection.commit()
        connection.close()

    first = inspect_sqlite_database(first_path)
    second = inspect_sqlite_database(second_path)

    assert first["schema_sha256"] == second["schema_sha256"]
    assert first["tables"][0]["content_sha256"] == second["tables"][0]["content_sha256"]
