"""Regression guard: keep the server on its SQLite-only pre-cutover adapter.

The shared connection factory supports Turso, but the application helper must
fail closed until a separately approved and fully tested cutover.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BACKEND_DIR / "server.py"


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                names.add(f"{func.value.id}.{func.attr}")
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def test_server_uses_sqlite_only_application_connection_before_cutover():
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    connection = _function(tree, "db_connection")
    calls = _call_names(connection)

    assert "StorageSettings.from_env" in calls
    assert "StorageSettings" in calls
    assert "open_sqlite_application_connection" in calls
    assert "open_storage_connection" not in calls
    assert "sqlite3.connect" not in calls


def test_server_database_path_is_derived_from_configured_data_directory():
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    assignments = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"BASE_DIR", "DB_PATH"}
    }

    assert {"BASE_DIR", "DB_PATH"} <= assignments.keys()

    base_source = ast.unparse(assignments["BASE_DIR"])
    db_source = ast.unparse(assignments["DB_PATH"])
    assert "CHAPPIE_DATA_DIR" in base_source
    assert "chappie_data" in base_source
    assert "BASE_DIR" in db_source
    assert "chappie_v16.sqlite3" in db_source
