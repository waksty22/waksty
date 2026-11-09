from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def test_server_database_connection_remains_on_guarded_sqlite_factory() -> None:
    tree = _tree(BACKEND / "server.py")
    function = _function(tree, "db_connection")
    calls = _called_names(function)

    assert "open_sqlite_application_connection" in calls
    assert "open_storage_connection" not in calls
    assert "connect" not in calls


def test_application_factory_refuses_turso_until_full_cutover() -> None:
    tree = _tree(BACKEND / "storage" / "connection_factory.py")
    function = _function(tree, "open_sqlite_application_connection")
    guarded = False
    raises_runtime_error = False

    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Attribute)
            and isinstance(test.left.value, ast.Name)
            and test.left.value.id == "selected"
            and test.left.attr == "backend"
            and any(
                isinstance(op, ast.NotEq)
                and isinstance(value, ast.Constant)
                and value.value == "sqlite"
                for op, value in zip(test.ops, test.comparators)
            )
        ):
            guarded = True
            raises_runtime_error = any(
                isinstance(child, ast.Raise)
                and isinstance(child.exc, ast.Call)
                and isinstance(child.exc.func, ast.Name)
                and child.exc.func.id == "RuntimeError"
                for child in ast.walk(node)
            )

    assert guarded
    assert raises_runtime_error


def test_database_path_is_derived_from_chappie_data_dir() -> None:
    tree = _tree(BACKEND / "server.py")
    assignments = {
        target.id: ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert "CHAPPIE_DATA_DIR" in assignments["BASE_DIR"]
    assert "./chappie_data" in assignments["BASE_DIR"]
    assert "BASE_DIR" in assignments["DB_PATH"]
    assert "chappie_v16.sqlite3" in assignments["DB_PATH"]


def test_local_backup_helpers_are_not_mistaken_for_remote_turso_backups() -> None:
    source = (BACKEND / "storage" / "backup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "local SQLite file backup" in source
    assert "sqlite3.connect" in source
    assert "libsql.connect" not in source
    assert "TURSO_DATABASE_URL" not in source
    assert _function(tree, "create_verified_backup")


def test_path_diagnostics_expose_mount_and_persistent_mount_indicators() -> None:
    source = (BACKEND / "storage" / "path_diagnostics.py").read_text(
        encoding="utf-8"
    )

    assert '"database_mount"' in source
    assert '"path_under_var_data"' in source
    assert '"is_root_filesystem"' in source
    assert '"read_only": True' in source
    assert '"data_contents_exposed": False' in source


def test_conversation_outbox_is_stored_in_the_application_database() -> None:
    source = (BACKEND / "memory" / "conversation_outbox.py").read_text(
        encoding="utf-8"
    )

    assert "sqlite3.Connection" in source
    assert "CREATE TABLE IF NOT EXISTS conversation_finalization_outbox" in source
    assert "UNIQUE(user_id, through_conversation_id)" in source
