"""V50.42 tests for the static SQL/backend-API inventory."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_sqlite_usage.py"
SPEC = importlib.util.spec_from_file_location("audit_sqlite_usage", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_inventory_is_static_and_does_not_open_database():
    report = AUDIT.build_report()
    assert report["static_only"] is True
    assert report["database_connections_opened"] == 0
    assert report["secrets_read"] is False
    assert report["files_scanned"] > 0
    assert report["finding_count"] >= 0


def test_inventory_finds_sqlite_backend_blockers_in_server():
    report = AUDIT.build_report()
    server = [item for item in report["findings"] if item["path"] == "backend/server.py"]
    categories = {item["category"] for item in server}
    assert "pragma" in categories
    assert "script_execution" in categories


def test_inventory_detects_critical_patterns_in_synthetic_source(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        'import sqlite3\n'
        'db = sqlite3.connect(":memory:")\n'
        'db.executescript("CREATE TABLE x(id INTEGER PRIMARY KEY AUTOINCREMENT)")\n'
        'db.backup(target)\n'
        'db.execute("PRAGMA journal_mode=WAL")\n'
        'cursor.lastrowid\n',
        encoding="utf-8",
    )
    findings = AUDIT.scan_file(source)
    categories = {item["category"] for item in findings}
    assert {"sqlite_connect", "script_execution", "native_backup", "pragma", "autoincrement"} <= categories


def test_report_is_deterministic():
    first = AUDIT.build_report()
    second = AUDIT.build_report()
    assert first == second
