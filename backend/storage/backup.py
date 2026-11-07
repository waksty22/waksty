"""Verified, local SQLite file backup and atomic restore helpers.

This module intentionally handles local SQLite files only. It does not attempt
to export, snapshot, or restore a remote Turso database.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any


def _database_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Fichier SQLite introuvable : {path}")
    return path


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _integrity_check(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            detail = result[0] if result else "aucun résultat"
            raise sqlite3.DatabaseError(f"Échec integrity_check : {detail}")
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(
        f"file:{source.as_posix()}?mode=ro", uri=True
    )
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def create_verified_backup(
    source_path: str | os.PathLike[str],
    backup_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Create a consistent SQLite backup and verify integrity plus checksum."""
    source = _database_path(source_path)
    destination = Path(backup_path).expanduser().resolve()
    if _same_file(source, destination):
        raise ValueError("La sauvegarde doit être un fichier distinct de la base.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.backup-{uuid.uuid4().hex}.tmp"
    )
    try:
        _copy_database(source, temporary)
        _integrity_check(temporary)
        checksum = _sha256(temporary)
        os.replace(temporary, destination)
        return {
            "path": str(destination),
            "sha256": checksum,
            "size_bytes": destination.stat().st_size,
            "integrity": "ok",
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def restore_verified_backup(
    backup_path: str | os.PathLike[str],
    target_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Validate a backup, preserve current DB, then atomically replace target.

    The returned rollback_path is a verified copy of the target as it existed
    immediately before restoration. Keep it until the restored application has
    been checked; restore it with this same function to roll back.
    """
    backup = _database_path(backup_path)
    target = _database_path(target_path)
    if _same_file(backup, target):
        raise ValueError("La sauvegarde et la base cible doivent être distinctes.")

    # Validate before touching the target or creating a rollback artifact.
    _integrity_check(backup)

    rollback = target.with_name(
        f"{target.name}.rollback-{uuid.uuid4().hex}.sqlite3"
    )
    staged = target.with_name(
        f".{target.name}.restore-{uuid.uuid4().hex}.tmp"
    )
    try:
        _copy_database(target, rollback)
        _integrity_check(rollback)
        _copy_database(backup, staged)
        _integrity_check(staged)
        os.replace(staged, target)
        return {
            "restored_from": str(backup),
            "target": str(target),
            "rollback_path": str(rollback),
            "integrity": "ok",
            "sha256": _sha256(target),
        }
    finally:
        if staged.exists():
            staged.unlink()
