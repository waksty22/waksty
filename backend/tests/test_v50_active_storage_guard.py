"""Regression guard: production storage stays on the explicitly audited SQLite path.

This is a temporary pre-cutover invariant. A future, separately approved
Turso cutover must replace these assertions with end-to-end backend tests.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BACKEND_DIR / "server.py"


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            assert isinstance(node, ast.FunctionDef)
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


def test_server_db_connection_remains_explicitly_sqlite_before_cutover():
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    connection = _function(tree, "db_connection")
    calls = _call_names(connection)

    assert "sqlite3.connect" in calls
    assert "open_storage_connection" not in calls
    assert "open_sqlite_application_connection" not in calls

    connect_calls = [
        node for node in ast.walk(connection)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sqlite3"
        and node.func.attr == "connect"
    ]
    assert len(connect_calls) == 1
    assert connect_calls[0].args
    assert isinstance(connect_calls[0].args[0], ast.Name)
    assert connect_calls[0].args[0].id == "DB_PATH"


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
