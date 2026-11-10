"""Read-only adapter for a single Hrana transaction used by logical backups.

The regular libsql DB-API HTTP connection is request-scoped and cannot keep
SAVEPOINT state across calls. This adapter accepts only SELECT statements and
normalizes Hrana ResultSet objects to the cursor subset used by logical_backup.
"""
from __future__ import annotations

import re
from typing import Any


class HranaBackupCursor:
    """Expose ResultSet columns and rows using the cursor API backup code needs."""

    def __init__(self, result: Any) -> None:
        self.description = tuple(
            (str(column), None, None, None, None, None, None)
            for column in result.columns
        )
        self._rows = [tuple(row) for row in result.rows]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class HranaTransactionConnection:
    """Read-only facade over one caller-owned Hrana transaction."""

    def __init__(self, transaction: Any) -> None:
        self._transaction = transaction

    def execute(self, sql: str) -> HranaBackupCursor:
        if (
            not isinstance(sql, str)
            or not re.match(r"(?i)^SELECT\b", sql.lstrip())
            or ";" in sql
        ):
            raise PermissionError("La sauvegarde Turso n'autorise que des requêtes SELECT uniques.")
        result = self._transaction.execute(sql)
        return HranaBackupCursor(result)
