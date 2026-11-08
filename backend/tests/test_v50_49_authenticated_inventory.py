from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from diagnostics.persistence_inventory import inspect_sqlite_database


def test_inventory_is_read_only_and_never_returns_private_values(tmp_path):
    database = tmp_path / "chappie.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE private_memories (content TEXT NOT NULL)")
    connection.execute("INSERT INTO private_memories VALUES (?)", ("secret-memory-value",))
    connection.commit()
    connection.close()
    before = database.read_bytes()

    report = inspect_sqlite_database(database)

    assert database.read_bytes() == before
    assert report["read_only"] is True
    assert report["database_contents_exposed"] is False
    assert report["integrity_check"]["ok"] is True
    assert report["total_rows"] == 1
    assert report["tables"][0]["table"] == "private_memories"
    assert report["tables"][0]["row_count"] == 1
    assert "secret-memory-value" not in repr(report)


def test_inventory_rejects_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    try:
        inspect_sqlite_database(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("A missing database must be rejected")


def test_authenticated_endpoint_inspects_only_configured_database(tmp_path, monkeypatch):
    import server

    database = tmp_path / "active.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE memory (content TEXT)")
    connection.execute("INSERT INTO memory VALUES ('private')")
    connection.commit()
    connection.close()

    monkeypatch.setattr(server, "DB_PATH", database)
    monkeypatch.setattr(server, "CHAPPIE_API_TOKEN", "test-token-only")
    client = TestClient(server.app)

    unauthorized = client.get("/api/system/persistence-inventory")
    assert unauthorized.status_code == 401

    authorized = client.get(
        "/api/system/persistence-inventory",
        headers={"Authorization": "Bearer test-token-only"},
    )
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["read_only"] is True
    assert payload["database_contents_exposed"] is False
    assert payload["total_rows"] == 1
    assert "private" not in repr(payload)


def test_inventory_endpoint_requires_existing_authentication_dependency():
    import server

    route = next(
        route for route in server.app.routes
        if getattr(route, "path", None) == "/api/system/persistence-inventory"
    )
    source = ast.get_source_segment(
        Path(server.__file__).read_text(encoding="utf-8"),
        next(
            node for node in ast.walk(ast.parse(Path(server.__file__).read_text(encoding="utf-8")))
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "system_persistence_inventory"
        ),
    )
    assert source is not None
    assert "Depends(require_auth)" in source
    assert route.methods == {"GET"}
