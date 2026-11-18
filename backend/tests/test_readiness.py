import sqlite3
from contextlib import contextmanager

from storage.readiness import check_database_readiness


def test_readiness_succeeds_when_core_table_is_queryable():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE emotional_state (user_id TEXT PRIMARY KEY)")
    db.commit()

    @contextmanager
    def connection_factory():
        yield db

    assert check_database_readiness(connection_factory) is True
    assert db.execute("SELECT COUNT(*) FROM emotional_state").fetchone()[0] == 0
    db.close()


def test_readiness_fails_closed_when_database_or_core_schema_is_unavailable():
    @contextmanager
    def unavailable_database():
        raise RuntimeError("private connection details must not escape")
        yield  # pragma: no cover

    assert check_database_readiness(unavailable_database) is False

    db = sqlite3.connect(":memory:")

    @contextmanager
    def incomplete_schema():
        yield db

    assert check_database_readiness(incomplete_schema) is False
    db.close()
