"""Read-only compatibility checks for the Turso/libsql driver.

These probes remain available for deployment diagnostics. The production
backend is selected separately through the guarded storage connection factory.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any


def inspect_turso_driver() -> dict[str, Any]:
    """Probe the configured remote driver without changing remote data.

    The probe performs SELECT/PRAGMA statements only. It never creates tables,
    writes rows, or changes the current Chappie database.
    """
    database_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    if not database_url or not auth_token:
        return {
            "configured": False,
            "connected": False,
            "compatible": False,
            "blockers": ["TURSO_DATABASE_URL ou TURSO_AUTH_TOKEN manquant"],
        }

    connection = None
    blockers: list[str] = []
    checks: dict[str, bool] = {}
    try:
        import libsql

        connection = libsql.connect(
            database=database_url,
            auth_token=auth_token,
        )
        checks["select"] = connection.execute("SELECT 1").fetchone()[0] == 1
        checks["sqlite_connection_type"] = isinstance(
            connection, sqlite3.Connection
        )

        try:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT 7 AS probe_value"
            ).fetchone()
            checks["sqlite_row_factory"] = (
                isinstance(row, sqlite3.Row)
                and row["probe_value"] == 7
            )
        except Exception:
            checks["sqlite_row_factory"] = False

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
            "sqlite_connection_type",
            "sqlite_row_factory",
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
        }
    except Exception as exc:
        # Do not return connection strings, credentials, or driver internals.
        return {
            "configured": True,
            "connected": False,
            "compatible": False,
            "blockers": ["Échec de la sonde distante: " + type(exc).__name__],
            "read_only": True,
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
