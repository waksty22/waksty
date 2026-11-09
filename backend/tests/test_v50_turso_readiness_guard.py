from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _tree(path: str) -> ast.AST:
    return ast.parse((BACKEND / path).read_text(encoding="utf-8"))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def _calls(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn = child.func
            if isinstance(fn, ast.Name):
                found.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                root = fn.value.id if isinstance(fn.value, ast.Name) else ""
                found.add(f"{root}.{fn.attr}" if root else fn.attr)
    return found


def test_server_stays_on_sqlite_only_connection_helper():
    server = _tree("server.py")
    calls = _calls(_function(server, "db_connection"))
    assert "open_sqlite_application_connection" in calls
    assert "open_storage_connection" not in calls


def test_turso_application_helper_fails_closed():
    factory = _tree("storage/connection_factory.py")
    helper = _function(factory, "open_sqlite_application_connection")
    source = ast.unparse(helper)
    assert "selected.backend" in source
    assert "!=" in source
    assert "sqlite" in source
    assert "RuntimeError" in source
    assert "Turso" in source


def test_remote_compatibility_probe_contains_no_data_mutation_calls():
    compat = _tree("storage/turso_compat.py")
    probe = _function(compat, "inspect_turso_driver")
    calls = _calls(probe)
    forbidden = {
        "insert", "update", "delete", "replace", "create", "drop", "alter",
        "executemany", "executescript", "commit",
    }
    assert not (calls & forbidden)
    source = ast.unparse(probe).upper()
    assert "SELECT 1" in source
    assert "PRAGMA TABLE_INFO" in source
    assert '"READ_ONLY": TRUE' in source or "'READ_ONLY': TRUE" in source
