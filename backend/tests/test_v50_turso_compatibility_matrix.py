"""V50.43 tests for the compatibility matrix."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_turso_compatibility_matrix.py"
SPEC = importlib.util.spec_from_file_location("build_turso_compatibility_matrix", SCRIPT)
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


def test_matrix_is_static_and_never_authorizes_activation():
    report = MATRIX.build_matrix()
    assert report["static_only"] is True
    assert report["database_connections_opened"] == 0
    assert report["secrets_read"] is False
    assert report["activation_allowed"] is False


def test_known_sqlite_blockers_are_classified():
    report = MATRIX.build_matrix()
    by_category = {row["category"]: row for row in report["matrix"]}
    assert by_category["pragma"]["classification"] == "À ADAPTER"
    assert by_category["script_execution"]["classification"] == "À ADAPTER"
    assert by_category["sqlite_connect"]["classification"] == "BLOQUANT AVANT BASCULE"


def test_every_finding_category_gets_a_validation_path():
    report = MATRIX.build_matrix()
    assert report["category_count"] > 0
    for row in report["matrix"]:
        assert row["occurrences"] > 0
        assert row["risk"].strip()
        assert row["required_validation"].strip()
        assert row["classification"].strip()


def test_matrix_is_deterministic():
    assert MATRIX.build_matrix() == MATRIX.build_matrix()
