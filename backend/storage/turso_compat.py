"""Read-only compatibility checks for Chappie's actual Turso DB-API adapter."""
from __future__ import annotations

import os
from typing import Any

from storage.libsql_adapter import LibSQLConnectionAdapter, adapt_libsql_connection


def inspect_turso_driver() -> dict[str, Any]:
    """Probe the same adapter used by production, without changing remote data."""
    database_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    if not database_url or not auth_token:
        return {
            "configured": False,
            "connected": False,
            "compatible": False,
            "blockers": ["TURSO_DATABASE_URL ou TURSO_AUTH_TOKEN manquant"],
            "read_only": True,
        }

    connection = None
    blockers: list[str] = []
    checks: dict[str, bool] = {}
    try:
        import libsql

        native = libsql.connect(database=database_url, auth_token=auth_token)
        connection = adapt_libsql_connection(native)
        checks["select"] = connection.execute("SELECT 1").fetchone()[0] == 1
        checks["production_adapter"] = isinstance(
            connection, LibSQLConnectionAdapter
        )
        row = connection.execute("SELECT 7 AS probe_value").fetchone()
        checks["named_row_access"] = (
            row is not None
            and row["probe_value"] == 7
            and row[0] == 7
        )
        checks["executescript"] = callable(
            getattr(connection, "executescript", None)
        )
        checks["lastrowid_attribute"] = hasattr(
            connection.execute("SELECT 1"), "lastrowid"
        )
        checks["pragma_table_info"] = connection.execute(
            "PRAGMA table_info(voice_profiles)"
        ).fetchall() is not None

        required = (
            "select",
            "production_adapter",
            "named_row_access",
            "executescript",
            "lastrowid_attribute",
            "pragma_table_info",
        )
        blockers.extend(name for name in required if not checks.get(name, False))
        return {
            "configured": True,
            "connected": True,
            "compatible": not blockers,
            "checks": checks,
            "blockers": blockers,
            "read_only": True,
            "data_contents_exposed": False,
            "compatibility_basis": "production_libsql_adapter",
        }
    except Exception as exc:
        return {
            "configured": True,
            "connected": False,
            "compatible": False,
            "blockers": ["Échec de la sonde distante: " + type(exc).__name__],
            "read_only": True,
            "data_contents_exposed": False,
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
