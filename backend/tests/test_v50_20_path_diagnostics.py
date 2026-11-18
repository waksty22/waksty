from __future__ import annotations

import sqlite3

from storage.path_diagnostics import inspect_sqlite_path_diagnostics


def test_path_diagnostics_reports_open_database_without_exposing_rows(tmp_path):
    database_path = tmp_path / "chappie.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE private_memory (content TEXT)")
        connection.execute("INSERT INTO private_memory VALUES (?)", ("secret-memory",))
        connection.commit()
        result = inspect_sqlite_path_diagnostics(
            connection=connection,
            configured_db_path=database_path,
            configured_data_dir=tmp_path,
            data_dir_env_configured=True,
        )
    finally:
        connection.close()

    assert result["read_only"] is True
    assert result["data_contents_exposed"] is False
    assert result["configured_path_matches_open_database"] is True
    assert result["opened_main_database_path"] == str(database_path.resolve())
    assert result["database_file"]["exists"] is True
    assert result["database_file"]["size_bytes"] > 0
    assert result["integrity_check"] == {
        "ok": True,
        "issue_count": 0,
        "issues": [],
        "issues_truncated": False,
    }
    assert "secret-memory" not in repr(result)
    assert "private_memory" not in repr(result)


def test_path_diagnostics_handles_in_memory_database(tmp_path):
    connection = sqlite3.connect(":memory:")
    try:
        result = inspect_sqlite_path_diagnostics(
            connection=connection,
            configured_db_path=tmp_path / "not-opened.sqlite3",
            configured_data_dir=tmp_path,
            data_dir_env_configured=False,
        )
    finally:
        connection.close()

    assert result["opened_main_database_path"] is None
    assert result["configured_path_matches_open_database"] is False
    assert result["database_file"]["exists"] is False
    assert result["integrity_check"]["ok"] is True
