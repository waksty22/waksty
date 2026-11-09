import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_server_db_connection_uses_factory_and_configured_db_path(
    monkeypatch, tmp_path
):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("CHAPPIE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CHAPPIE_SQLITE_PATH", raising=False)
    database_path = tmp_path / "actual" / "chappie.sqlite3"
    monkeypatch.setattr(server, "DB_PATH", database_path)

    connection = server.db_connection()
    try:
        connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        connection.commit()
        assert database_path.is_file()
        assert connection.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0
    finally:
        connection.close()


def test_server_refuses_turso_startup_without_cutover_marker(monkeypatch):
    import server

    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "turso")
    monkeypatch.delenv("CHAPPIE_TURSO_CUTOVER_READY", raising=False)

    with pytest.raises(RuntimeError, match="CHAPPIE_TURSO_CUTOVER_READY"):
        server.init_db()
