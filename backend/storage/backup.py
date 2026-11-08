"""Verified, local SQLite file backup and atomic restore helpers.

This module intentionally handles local SQLite files only. It does not attempt
to export, snapshot, or restore a remote Turso database.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
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


def _checksum_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha256")


def _write_checksum_no_clobber(path: Path, digest: str) -> Path:
    """Atomically publish a checksum sidecar without replacing an existing one."""
    sidecar = _checksum_path(path)
    fd, temporary_name = tempfile.mkstemp(
        prefix=sidecar.name + ".", suffix=".tmp", dir=sidecar.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(f"{digest}  {path.name}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, sidecar)
        return sidecar
    finally:
        temporary.unlink(missing_ok=True)


def _verify_checksum(path: Path) -> str:
    """Require a well-formed SHA-256 sidecar and return the verified digest."""
    sidecar = _checksum_path(path)
    try:
        fields = sidecar.read_text(encoding="ascii").strip().split()
    except FileNotFoundError as exc:
        raise sqlite3.DatabaseError(
            f"Checksum absent pour la sauvegarde : {path.name}"
        ) from exc
    if (
        len(fields) != 2
        or fields[1] != path.name
        or len(fields[0]) != 64
        or any(char not in "0123456789abcdef" for char in fields[0].lower())
    ):
        raise sqlite3.DatabaseError("Fichier checksum invalide.")
    actual = _sha256(path)
    if not hmac.compare_digest(actual, fields[0].lower()):
        raise sqlite3.DatabaseError("Checksum SHA-256 invalide pour la sauvegarde.")
    return actual


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
    """Create a no-clobber SQLite backup with a durable SHA-256 sidecar."""
    source = _database_path(source_path)
    destination = Path(backup_path).expanduser().resolve()
    sidecar = _checksum_path(destination)
    if _same_file(source, destination):
        raise ValueError("La sauvegarde doit être un fichier distinct de la base.")
    if destination.exists() or sidecar.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing backup or checksum: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".backup-", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    published_backup = False
    published_checksum = False
    try:
        _copy_database(source, temporary)
        _integrity_check(temporary)
        checksum = _sha256(temporary)
        # Same-directory hard-link publication is atomic and never clobbers.
        os.link(temporary, destination)
        published_backup = True
        _write_checksum_no_clobber(destination, checksum)
        published_checksum = True
        return {
            "path": str(destination),
            "checksum_path": str(sidecar),
            "sha256": checksum,
            "size_bytes": destination.stat().st_size,
            "integrity": "ok",
            "checksum_verified": True,
        }
    except Exception:
        if published_checksum:
            sidecar.unlink(missing_ok=True)
        if published_backup:
            destination.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def restore_verified_backup(
    backup_path: str | os.PathLike[str],
    target_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify checksum/integrity, preserve target, then atomically replace it.

    The rollback database and its checksum sidecar are retained after success.
    They can be passed back to this function to undo the restore.
    """
    backup = _database_path(backup_path)
    target = _database_path(target_path)
    if _same_file(backup, target):
        raise ValueError("La sauvegarde et la base cible doivent être distinctes.")

    # Verify the checksum before integrity checks, rollback copies, or target IO.
    backup_digest = _verify_checksum(backup)
    _integrity_check(backup)

    rollback = target.with_name(
        f"{target.name}.rollback-{uuid.uuid4().hex}.sqlite3"
    )
    rollback_temp = target.with_name(
        f".{rollback.name}.{uuid.uuid4().hex}.tmp"
    )
    staged = target.with_name(
        f".{target.name}.restore-{uuid.uuid4().hex}.tmp"
    )
    rollback_published = False
    restore_committed = False
    try:
        _copy_database(target, rollback_temp)
        _integrity_check(rollback_temp)
        rollback_digest = _sha256(rollback_temp)
        os.link(rollback_temp, rollback)
        rollback_published = True
        _write_checksum_no_clobber(rollback, rollback_digest)

        _copy_database(backup, staged)
        _integrity_check(staged)
        os.replace(staged, target)
        restore_committed = True
        return {
            "restored_from": str(backup),
            "target": str(target),
            "backup_sha256": backup_digest,
            "rollback_path": str(rollback),
            "rollback_checksum_path": str(_checksum_path(rollback)),
            "rollback_sha256": rollback_digest,
            "integrity": "ok",
            "sha256": _sha256(target),
        }
    finally:
        rollback_temp.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
        if rollback_published and not restore_committed:
            rollback.unlink(missing_ok=True)
            _checksum_path(rollback).unlink(missing_ok=True)
