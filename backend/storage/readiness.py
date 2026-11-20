"""Read-only database readiness checks for Chappie's HTTP probes."""


def check_database_readiness(connection_factory) -> bool:
    """Return whether the selected database is reachable and has core schema.

    No rows are read or changed. Exceptions are intentionally collapsed into
    a boolean so driver details, URLs, and credentials never reach HTTP probes.
    """
    try:
        with connection_factory() as db:
            db.execute("SELECT 1 FROM emotional_state LIMIT 1").fetchone()
    except Exception:
        return False
    return True
