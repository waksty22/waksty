from __future__ import annotations

import sqlite3
import sys
import types

from storage.turso_compat import inspect_turso_driver


def test_turso_compatibility_checks_the_production_adapter(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test.invalid")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")
    monkeypatch.setitem(
        sys.modules,
        "libsql",
        types.SimpleNamespace(
            connect=lambda **kwargs: sqlite3.connect(":memory:")
        ),
    )

    result = inspect_turso_driver()

    assert result["configured"] is True
    assert result["connected"] is True
    assert result["compatible"] is True
    assert result["read_only"] is True
    assert result["data_contents_exposed"] is False
    assert result["compatibility_basis"] == "production_libsql_adapter"
    assert result["blockers"] == []
    assert result["checks"]["production_adapter"] is True
    assert result["checks"]["named_row_access"] is True
    assert "sqlite_connection_type" not in result["checks"]
    assert "sqlite_row_factory" not in result["checks"]
