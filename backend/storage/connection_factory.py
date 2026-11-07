"""V50 storage connection factory (pre-cutover).

This factory is deliberately not wired into server.db_connection yet.
SQLite remains the production default until the full backend contract,
schema migration, backup/restore and rollback have passed review.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.libsql_adapter import adapt_libsql_connection


@dataclass(frozen=True)
class StorageSettings:
    backend: str = "sqlite"
    sqlite_path: str = "./chappie_data/chappie_v16.sqlite3"
    turso_database_url: str = ""
    turso_auth_token: str = ""

    @classmethod
    def from_env(cls) -> "StorageSettings":
        backend = os.getenv("CHAPPIE_STORAGE_BACKEND", "sqlite").strip().lower()
        if backend not in {"sqlite", "turso"}:
            raise ValueError("CHAPPIE_STORAGE_BACKEND doit être sqlite ou turso.")
        return cls(
            backend=backend,
            sqlite_path=os.getenv(
                "CHAPPIE_SQLITE_PATH",
                "./chappie_data/chappie_v16.sqlite3",
            ).strip(),
            turso_database_url=os.getenv("TURSO_DATABASE_URL", "").strip(),
            turso_auth_token=os.getenv("TURSO_AUTH_TOKEN", "").strip(),
        )


def open_storage_connection(settings: StorageSettings | None = None) -> Any:
    """Open an explicitly selected connection; never changes the selection itself."""
    selected = settings or StorageSettings.from_env()

    if selected.backend == "sqlite":
        path = Path(selected.sqlite_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path),
            timeout=20,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=20000")
        return connection

    if selected.backend == "turso":
        if not selected.turso_database_url or not selected.turso_auth_token:
            raise ValueError(
                "Le mode Turso exige TURSO_DATABASE_URL et TURSO_AUTH_TOKEN."
            )
        try:
            import libsql
        except ImportError as exc:
            raise RuntimeError(
                "Le paquet libsql est requis pour le mode Turso."
            ) from exc

        native = libsql.connect(
            database=selected.turso_database_url,
            auth_token=selected.turso_auth_token,
        )
        connection = adapt_libsql_connection(native)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    raise ValueError("Backend de stockage non pris en charge.")
