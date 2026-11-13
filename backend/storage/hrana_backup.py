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


def describe_hrana_error(error: BaseException) -> dict[str, Any]:
    """Return safe diagnostic fields without exposing URLs, headers, or credentials."""
    status = getattr(error, "status", None)
    reason = getattr(error, "message", None)
    if not isinstance(reason, str):
        reason = ""
    return {
        "error_type": type(error).__name__,
        "status": status if isinstance(status, (int, str)) else None,
        "reason": reason[:160],
    }


class HranaRestoreCursor:
    """Minimal DB-API cursor facade for guarded logical restore."""

    def __init__(self, result: Any) -> None:
        self.description = tuple(
            (str(column), None, None, None, None, None, None)
            for column in result.columns
        )
        self._rows = [tuple(row) for row in result.rows]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class HranaRestoreConnection:
    """Write-capable facade restricted to one caller-owned restore transaction.

    The caller must open HranaHttpClient.transaction() first and must verify
    the destination identity independently before constructing this adapter.
    """

    def __init__(self, transaction: Any) -> None:
        self._transaction = transaction
        self.in_transaction = True

    def execute(self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()) -> HranaRestoreCursor:
        result = self._transaction.execute_write(sql, parameters)
        return HranaRestoreCursor(result)

    def executemany(self, sql: str, parameter_rows: list[tuple[Any, ...]]) -> None:
        for parameters in parameter_rows:
            self._transaction.execute_write(sql, parameters)

    def commit(self) -> None:
        if self.in_transaction:
            self._transaction.commit()
            self.in_transaction = False

    def rollback(self) -> None:
        if self.in_transaction:
            self._transaction.rollback()
            self.in_transaction = False
