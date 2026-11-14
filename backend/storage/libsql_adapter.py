"""DB-API compatibility wrappers used by the opt-in Turso storage backend.

The adapter normalizes libsql rows, cursors, transactions and common database
errors to the subset of sqlite3 behavior used by Chappie's backend.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from typing import Any


class CompatRow(Sequence[Any]):
    """Tuple-like row with sqlite3.Row-style indexed and named lookup."""

    __slots__ = ("_values", "_names", "_index")

    def __init__(self, values: Iterable[Any], names: Iterable[str]) -> None:
        self._values = tuple(values)
        self._names = tuple(names)
        self._index = {name.casefold(): i for i, name in enumerate(self._names)}

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, str):
            try:
                key = self._index[key.casefold()]
            except KeyError as exc:
                raise IndexError(f"No such column: {key}") from exc
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def keys(self) -> list[str]:
        return list(self._names)

    def as_dict(self) -> dict[str, Any]:
        return dict(zip(self._names, self._values))


class CompatCursor:
    """Normalize cursor rows and expose the attributes used by Chappie."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        description = getattr(cursor, "description", None) or ()
        self.description = tuple(description)
        self._names = tuple(
            item[0] if isinstance(item, (tuple, list)) else str(item)
            for item in self.description
        )

    @property
    def lastrowid(self) -> int | None:
        return getattr(self._cursor, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", -1))

    def _row(self, row: Any) -> CompatRow | None:
        if row is None:
            return None
        if isinstance(row, CompatRow):
            return row
        if isinstance(row, dict):
            return CompatRow(row.values(), row.keys())
        if not self._names:
            raise RuntimeError(
                "Le pilote libsql n'a fourni aucun nom de colonne pour une ligne."
            )
        return CompatRow(row, self._names)

    def fetchone(self) -> CompatRow | None:
        return self._row(self._cursor.fetchone())

    def fetchall(self) -> list[CompatRow]:
        return [self._row(row) for row in self._cursor.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[CompatRow]:
        rows = (
            self._cursor.fetchmany()
            if size is None
            else self._cursor.fetchmany(size)
        )
        return [self._row(row) for row in rows]

    def __iter__(self) -> Iterator[CompatRow]:
        # libsql-python's native Cursor is not iterable (unlike sqlite3.Cursor).
        # Repeated fetchone() preserves streaming behavior across both drivers.
        while True:
            row = self._cursor.fetchone()
            if row is None:
                break
            converted = self._row(row)
            if converted is not None:
                yield converted


def _raise_sqlite_compatible_error(exc: Exception) -> None:
    """Translate libsql's DB-API exception classes into sqlite3 equivalents."""
    if isinstance(exc, sqlite3.Error):
        raise exc
    error_types = {
        "OperationalError": sqlite3.OperationalError,
        "IntegrityError": sqlite3.IntegrityError,
        "ProgrammingError": sqlite3.ProgrammingError,
        "DataError": sqlite3.DataError,
        "InterfaceError": sqlite3.InterfaceError,
        "DatabaseError": sqlite3.DatabaseError,
        "NotSupportedError": sqlite3.NotSupportedError,
        "InternalError": sqlite3.InternalError,
    }
    error_class = error_types.get(type(exc).__name__)
    message = str(exc)
    lowered = message.casefold()

    # libsql-python 0.1.x reports some SQLite engine failures as ValueError.
    # Translate only recognizable database diagnostics; leave unrelated
    # ValueErrors untouched.
    if isinstance(exc, ValueError):
        if any(marker in lowered for marker in (
            "no such table",
            "no such column",
            "syntax error",
            "database is locked",
            "database or disk is full",
            "unable to open database",
            "not a database",
        )):
            error_class = sqlite3.OperationalError
        elif "constraint failed" in lowered:
            error_class = sqlite3.IntegrityError

    if error_class is not None:
        raise error_class(message) from exc
    raise exc


class LibSQLConnectionAdapter:
    """Provide the subset of sqlite3.Connection used by the current backend."""

    def __init__(
        self, connection: Any, *, close_on_context_exit: bool = False
    ) -> None:
        self._connection = connection
        self._closed = False
        self._close_on_context_exit = close_on_context_exit

    def _ensure_open(self) -> None:
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

    def execute(self, sql: str, parameters: Any = ()) -> CompatCursor:
        self._ensure_open()
        try:
            return CompatCursor(self._connection.execute(sql, parameters))
        except Exception as exc:
            _raise_sqlite_compatible_error(exc)

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Sequence[Any]]
    ) -> CompatCursor:
        self._ensure_open()
        try:
            return CompatCursor(
                self._connection.executemany(sql, seq_of_parameters)
            )
        except Exception as exc:
            _raise_sqlite_compatible_error(exc)

    def executescript(self, script: str) -> None:
        """Delegate script execution to libsql's native implementation."""
        self._ensure_open()
        execute_script = getattr(self._connection, "executescript", None)
        if not callable(execute_script):
            raise NotImplementedError(
                "Le pilote libsql ne fournit pas executescript()."
            )
        try:
            execute_script(script)
        except Exception as exc:
            _raise_sqlite_compatible_error(exc)

    def commit(self) -> None:
        self._ensure_open()
        try:
            self._connection.commit()
        except Exception as exc:
            _raise_sqlite_compatible_error(exc)

    def rollback(self) -> None:
        self._ensure_open()
        try:
            self._connection.rollback()
        except Exception as exc:
            _raise_sqlite_compatible_error(exc)

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "LibSQLConnectionAdapter":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        # Preserve sqlite3 transaction semantics. Request-scoped adapters
        # additionally release their remote session after the transaction.
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            if self._close_on_context_exit:
                self.close()
        return False


def adapt_libsql_connection(
    connection: Any, *, close_on_context_exit: bool = False
) -> LibSQLConnectionAdapter:
    """Wrap a libsql connection; optionally release request-scoped sessions."""
    return LibSQLConnectionAdapter(
        connection, close_on_context_exit=close_on_context_exit
    )
