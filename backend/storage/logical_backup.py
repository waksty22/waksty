"""Portable, read-only logical export for a libSQL/Turso connection.

This module never opens a connection, reads credentials, or contacts Turso by
itself. The caller supplies an already-open connection and an explicit output
path. It exports schema and rows, then verifies the artifact in isolated
SQLite before returning its checksum.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


def _value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__type__": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported database value type: {type(value).__name__}")


def _restore_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type__") == "blob":
        return base64.b64decode(value["base64"], validate=True)
    return value


def _query_rows(connection: Any, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    cursor = connection.execute(sql)
    description = cursor.description
    if not description:
        return [], []
    names = [str(column[0]) for column in description]
    rows = cursor.fetchall()
    return names, [tuple(row) for row in rows]


def export_logical_backup(
    connection: Any,
    destination: str | Path,
    *,
    manage_snapshot: bool = True,
) -> dict[str, Any]:
    """Export all user tables without writing to the DB.

    SQLite connections manage a savepoint by default. For clients such as
    libSQL/Hrana, callers may supply an already-open transaction and set
    ``manage_snapshot=False``; the caller then owns commit/rollback and keeps
    every read on that same transaction snapshot.
    """
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    objects_sql = """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1
                           WHEN 'view' THEN 2 ELSE 3 END, name
    """
    # A savepoint pins one read snapshot for the entire multi-table export.
    # It nests safely inside a caller transaction and never writes user data.
    snapshot = "chappie_logical_backup_snapshot"
    if manage_snapshot:
        connection.execute(f"SAVEPOINT {snapshot}")
    try:
        _, object_rows = _query_rows(connection, objects_sql)
        objects = [
            {"type": str(row[0]), "name": str(row[1]), "table": str(row[2]), "sql": row[3]}
            for row in object_rows
        ]
        tables = []
        total_rows = 0
        for obj in objects:
            if obj["type"] != "table":
                continue
            table_name = obj["name"]
            escaped = '"' + table_name.replace('"', '""') + '"'
            if isinstance(obj.get("sql"), str) and "CREATE VIRTUAL TABLE" in obj["sql"].upper():
                raise ValueError(f"Unsupported virtual table in logical backup: {table_name}")
            _, column_info = _query_rows(connection, f"PRAGMA table_xinfo({escaped})")
            if not column_info:
                raise ValueError(f"Unable to inspect columns for logical backup table: {table_name}")
            # hidden=0 are writable columns; generated/virtual hidden columns
            # are recomputed by SQLite and must not be included in INSERT.
            columns = [str(row[1]) for row in column_info if int(row[6]) == 0]
            if not columns:
                raise ValueError(f"Table has no writable columns: {table_name}")
            selected = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
            _, rows = _query_rows(connection, f"SELECT {selected} FROM {escaped}")
            encoded_rows = [[_value(value) for value in row] for row in rows]
            tables.append({"name": table_name, "columns": columns, "rows": encoded_rows})
            total_rows += len(encoded_rows)

        autoincrement_tables = {
            obj["name"] for obj in objects
            if obj["type"] == "table" and isinstance(obj.get("sql"), str)
            and "AUTOINCREMENT" in obj["sql"].upper()
        }
        sequences = []
        if autoincrement_tables:
            _, sequence_rows = _query_rows(connection, "SELECT name, seq FROM sqlite_sequence")
            sequences = [
                {"table": str(name), "seq": int(seq)}
                for name, seq in sequence_rows if name in autoincrement_tables
            ]
    except Exception:
        if manage_snapshot:
            connection.execute(f"ROLLBACK TO SAVEPOINT {snapshot}")
        raise
    finally:
        if manage_snapshot:
            connection.execute(f"RELEASE SAVEPOINT {snapshot}")

    payload = {
        "format": "chappie-turso-logical-backup",
        "format_version": 1,
        "objects": objects,
        "tables": tables,
        "sequences": sequences,
        "summary": {
            "table_count": len(tables),
            "object_count": len(objects),
            "total_rows": total_rows,
            "row_counts": {table["name"]: len(table["rows"]) for table in tables},
        },
    }
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    digest = hashlib.sha256(encoded).hexdigest()
    checksum_path = destination.with_suffix(destination.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    verification = verify_logical_backup(destination)
    if not verification["valid"]:
        raise ValueError("Backup export failed local restore verification.")
    return {
        "path": str(destination),
        "sha256": digest,
        "size_bytes": len(encoded),
        "verified": True,
        **payload["summary"],
    }


def verify_logical_backup(path: str | Path) -> dict[str, Any]:
    """Restore an export into a temporary SQLite DB and verify its integrity."""
    path = Path(path).expanduser().resolve()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not checksum_path.exists():
        return {"valid": False, "reason": "checksum_missing", "sha256": digest}
    expected = checksum_path.read_text(encoding="ascii").split()[0]
    if digest != expected:
        return {"valid": False, "reason": "checksum_mismatch", "sha256": digest}
    payload = json.loads(raw)
    if payload.get("format") != "chappie-turso-logical-backup" or payload.get("format_version") != 1:
        return {"valid": False, "reason": "unsupported_format", "sha256": digest}

    db = sqlite3.connect(":memory:")
    try:
        db.execute("PRAGMA foreign_keys = OFF")
        objects = payload["objects"]
        for obj in objects:
            if obj["type"] == "table" and obj["sql"]:
                db.execute(obj["sql"])
        for table in payload["tables"]:
            columns = table["columns"]
            if not columns:
                continue
            table_sql = '"' + table["name"].replace('"', '""') + '"'
            placeholders = ",".join("?" for _ in columns)
            column_sql = ",".join('"' + col.replace('"', '""') + '"' for col in columns)
            db.executemany(
                f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders})",
                [[_restore_value(value) for value in row] for row in table["rows"]],
            )
        for sequence in payload.get("sequences", []):
            db.execute("DELETE FROM sqlite_sequence WHERE name = ?", (sequence["table"],))
            db.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                (sequence["table"], sequence["seq"]),
            )
        for obj in objects:
            if obj["type"] in {"index", "view", "trigger"} and obj["sql"]:
                db.execute(obj["sql"])
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = db.execute("PRAGMA foreign_key_check").fetchall()
        restored_counts = {
            table["name"]: db.execute(
                'SELECT COUNT(*) FROM "' + table["name"].replace('"', '""') + '"'
            ).fetchone()[0]
            for table in payload["tables"]
        }
        expected_counts = payload["summary"]["row_counts"]
        counts_match = restored_counts == expected_counts
        valid = integrity == "ok" and not fk_violations and counts_match
        return {
            "valid": valid,
            "sha256": digest,
            "integrity_check": integrity,
            "foreign_key_violations": len(fk_violations),
            "row_counts_match": counts_match,
            "table_count": len(restored_counts),
            "total_rows": sum(restored_counts.values()),
        }
    finally:
        db.close()



def restore_logical_backup_payload(
    connection: Any,
    payload: dict[str, Any],
    *,
    target_identity: str,
    expected_target_identity: str,
    production_identity: str,
) -> dict[str, Any]:
    """Restore a verified logical payload into an explicitly identified empty target."""
    identities = (target_identity.strip(), expected_target_identity.strip(), production_identity.strip())
    if not all(identities) or identities[0] != identities[1]:
        raise PermissionError("La cible ne correspond pas à l'identité explicitement attendue.")
    if identities[0].casefold() == identities[2].casefold():
        raise PermissionError("La restauration vers l'identité de production est interdite.")
    if not isinstance(payload, dict) or payload.get("format") != "chappie-turso-logical-backup" or payload.get("format_version") != 1:
        raise ValueError("Format de sauvegarde logique non pris en charge.")

    objects, tables, summary = payload.get("objects"), payload.get("tables"), payload.get("summary")
    if not isinstance(objects, list) or not isinstance(tables, list) or not isinstance(summary, dict):
        raise ValueError("Structure de sauvegarde incomplète.")
    if not all(isinstance(obj, dict) for obj in objects) or not all(isinstance(table, dict) for table in tables):
        raise ValueError("Entrées de schéma ou de tables invalides.")
    supported_types = {"table", "index", "view", "trigger"}
    if any(obj.get("type") not in supported_types for obj in objects):
        raise ValueError("Type d'objet de schéma non pris en charge.")
    schema_names = [obj.get("name") for obj in objects]
    if any(not isinstance(name, str) or not name or name.startswith("sqlite_") for name in schema_names):
        raise ValueError("Nom d'objet de schéma invalide.")
    if len(set(schema_names)) != len(schema_names):
        raise ValueError("Noms d'objets de schéma dupliqués.")
    table_objects = [obj for obj in objects if obj.get("type") == "table"]
    object_names = {obj["name"] for obj in table_objects}
    table_names = [table.get("name") for table in tables]
    if any(not isinstance(name, str) or not name or name.startswith("sqlite_") for name in table_names):
        raise ValueError("Nom de table invalide.")
    if len(set(table_names)) != len(table_names) or set(table_names) != object_names:
        raise ValueError("Les tables et les objets de schéma ne correspondent pas.")
    expected_counts = summary.get("row_counts")
    if not isinstance(expected_counts, dict) or set(expected_counts) != set(table_names):
        raise ValueError("Comptage des lignes attendu invalide.")
    if any(type(count) is not int or count < 0 for count in expected_counts.values()):
        raise ValueError("Comptage des lignes attendu invalide.")
    normalized_expected = dict(expected_counts)
    if type(summary.get("total_rows")) is not int or summary["total_rows"] != sum(normalized_expected.values()):
        raise ValueError("Résumé du nombre total de lignes incohérent.")
    autoincrement_tables = {
        obj["name"] for obj in table_objects
        if isinstance(obj.get("sql"), str) and "AUTOINCREMENT" in obj["sql"].upper()
    }
    sequences = payload.get("sequences", [])
    if not isinstance(sequences, list) or not all(isinstance(item, dict) for item in sequences):
        raise ValueError("Séquences AUTOINCREMENT invalides.")
    sequence_names = [item.get("table") for item in sequences]
    if (
        any(name not in autoincrement_tables for name in sequence_names)
        or len(set(sequence_names)) != len(sequence_names)
        or any(type(item.get("seq")) is not int or item["seq"] < 0 for item in sequences)
    ):
        raise ValueError("Séquences AUTOINCREMENT invalides.")

    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "AND type IN ('table', 'index', 'view', 'trigger')"
    ).fetchall()
    if existing:
        raise PermissionError("La base cible n'est pas vide ; aucune donnée n'a été modifiée.")

    owns_transaction = not bool(getattr(connection, "in_transaction", False))
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        # Defer FK enforcement until the complete dataset has been inserted;
        # this avoids depending on alphabetic/table creation order.
        connection.execute("PRAGMA defer_foreign_keys = ON")
        for obj in table_objects:
            sql = obj.get("sql")
            if not isinstance(sql, str) or not sql.lstrip().upper().startswith("CREATE TABLE"):
                raise ValueError("Instruction CREATE TABLE invalide dans la sauvegarde.")
            connection.execute(sql)

        restored_counts: dict[str, int] = {}
        for table in tables:
            name, columns, rows = table["name"], table.get("columns"), table.get("rows")
            if not isinstance(columns, list) or not columns or not all(isinstance(col, str) for col in columns) or not isinstance(rows, list):
                raise ValueError("Colonnes ou lignes de table invalides.")
            quoted_table = '"' + name.replace('"', '""') + '"'
            quoted_columns = ",".join('"' + col.replace('"', '""') + '"' for col in columns)
            placeholders = ",".join("?" for _ in columns)
            decoded_rows = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(columns):
                    raise ValueError("Une ligne ne correspond pas aux colonnes déclarées.")
                decoded_rows.append([_restore_value(value) for value in row])
            if decoded_rows:
                connection.executemany(
                    f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})",
                    decoded_rows,
                )
            restored_counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0])

        for sequence in sequences:
            connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", (sequence["table"],))
            connection.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                (sequence["table"], sequence["seq"]),
            )

        for obj in objects:
            if obj.get("type") in {"index", "view", "trigger"}:
                sql = obj.get("sql")
                normalized_sql = sql.lstrip().upper() if isinstance(sql, str) else ""
                valid_prefix = (
                    normalized_sql.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX"))
                    if obj["type"] == "index"
                    else normalized_sql.startswith("CREATE VIEW")
                    if obj["type"] == "view"
                    else normalized_sql.startswith("CREATE TRIGGER")
                )
                if not valid_prefix:
                    raise ValueError("Instruction de schéma invalide dans la sauvegarde.")
                connection.execute(sql)

        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("La restauration contient des violations de clés étrangères.")
        if restored_counts != normalized_expected:
            raise ValueError("Les nombres de lignes restaurés ne correspondent pas à la sauvegarde.")
        if owns_transaction:
            connection.commit()
        return {
            "restored": True, "target_identity": identities[0],
            "table_count": len(restored_counts), "total_rows": sum(restored_counts.values()),
            "row_counts": restored_counts, "foreign_key_violations": 0,
        }
    except Exception:
        if owns_transaction:
            connection.rollback()
        raise


def export_encrypted_logical_backup(
    connection: Any,
    destination: str | Path,
    encryption_key: str,
    *,
    manage_snapshot: bool = True,
) -> dict[str, Any]:
    """Write only an AES-GCM encrypted logical backup; plaintext stays temporary."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import secrets

    if not isinstance(encryption_key, str) or len(encryption_key) < 12:
        raise ValueError("Une clé de chiffrement d'au moins 12 caractères est requise.")
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chappie-logical-") as work:
        plain_path = Path(work) / "snapshot.json"
        result = export_logical_backup(
            connection, plain_path, manage_snapshot=manage_snapshot
        )
        plaintext = plain_path.read_bytes()
        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
        key = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000
        ).derive(encryption_key.encode("utf-8"))
        encrypted = b"CHAPPIE-LOGICAL-V1" + salt + nonce + AESGCM(key).encrypt(
            nonce, plaintext, b"CHAPPIE-LOGICAL-V1"
        )
        temporary = destination.with_name("." + destination.name + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    digest = hashlib.sha256(encrypted).hexdigest()
    checksum_path = destination.with_suffix(destination.suffix + ".sha256")
    if checksum_path.exists():
        destination.unlink(missing_ok=True)
        raise FileExistsError(f"Refusing to overwrite existing checksum: {checksum_path}")
    checksum_temporary = checksum_path.with_name("." + checksum_path.name + ".tmp")
    try:
        with checksum_temporary.open("x", encoding="ascii") as handle:
            handle.write(f"{digest}  {destination.name}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(checksum_temporary, checksum_path)
        # Verify the exact ciphertext artifact on disk, including checksum,
        # AES-GCM authentication, decryption, and logical restore integrity.
        verification = verify_encrypted_logical_backup(destination, encryption_key)
        if not verification.get("valid"):
            raise ValueError(
                "Encrypted backup failed final on-disk verification: "
                + str(verification.get("reason", "unknown"))
            )
    except Exception:
        destination.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        checksum_temporary.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "sha256": digest,
        "size_bytes": len(encrypted),
        "verified": True,
        "encrypted": True,
        "encryption": "AES-256-GCM/PBKDF2-SHA256-600000",
        "verification": {
            "checksum": True,
            "decryption": True,
            "restore_integrity": True,
        },
        "table_count": result["table_count"],
        "total_rows": result["total_rows"],
    }


def verify_encrypted_logical_backup(
    path: str | Path, encryption_key: str
) -> dict[str, Any]:
    """Decrypt into a private temporary directory and verify without altering DBs."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    path = Path(path).expanduser().resolve()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not checksum_path.exists() or checksum_path.read_text(encoding="ascii").split()[0] != digest:
        return {"valid": False, "reason": "checksum_missing_or_mismatch"}
    magic = b"CHAPPIE-LOGICAL-V1"
    if not raw.startswith(magic) or len(raw) < len(magic) + 28:
        return {"valid": False, "reason": "invalid_format"}
    if not isinstance(encryption_key, str) or len(encryption_key) < 12:
        return {"valid": False, "reason": "invalid_key"}
    offset = len(magic)
    salt, nonce = raw[offset:offset + 16], raw[offset + 16:offset + 28]
    key = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000
    ).derive(encryption_key.encode("utf-8"))
    try:
        plaintext = AESGCM(key).decrypt(nonce, raw[offset + 28:], magic)
    except Exception:
        return {"valid": False, "reason": "decryption_failed"}
    with tempfile.TemporaryDirectory(prefix="chappie-logical-verify-") as work:
        plain_path = Path(work) / "snapshot.json"
        plain_path.write_bytes(plaintext)
        plain_path.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(plaintext).hexdigest()}  snapshot.json\n",
            encoding="ascii",
        )
        result = verify_logical_backup(plain_path)
    return {**result, "encrypted": True, "encryption": "AES-256-GCM"}



def restore_encrypted_logical_backup(
    connection: Any,
    path: str | Path,
    encryption_key: str,
    *,
    target_identity: str,
    expected_target_identity: str,
    production_identity: str,
) -> dict[str, Any]:
    """Authenticate and verify one encrypted artifact before restoring its payload.

    The ciphertext is read once so verification and restoration operate on the
    same bytes. AES-GCM authentication protects the payload; the adjacent
    checksum detects damaged or mismatched artifact files.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    artifact = Path(path).expanduser().resolve()
    raw = artifact.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    checksum_path = artifact.with_suffix(artifact.suffix + ".sha256")
    if not checksum_path.exists():
        raise ValueError("Checksum de sauvegarde absent.")
    try:
        expected_digest = checksum_path.read_text(encoding="ascii").split()[0]
    except (OSError, UnicodeError, IndexError):
        raise ValueError("Checksum de sauvegarde invalide.") from None
    if digest != expected_digest:
        raise ValueError("Checksum de sauvegarde incorrect.")

    magic = b"CHAPPIE-LOGICAL-V1"
    if not raw.startswith(magic) or len(raw) < len(magic) + 28:
        raise ValueError("Format de sauvegarde chiffrée invalide.")
    if not isinstance(encryption_key, str) or len(encryption_key) < 12:
        raise ValueError("Clé de chiffrement invalide.")
    offset = len(magic)
    salt, nonce = raw[offset:offset + 16], raw[offset + 16:offset + 28]
    derived_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000
    ).derive(encryption_key.encode("utf-8"))
    try:
        plaintext = AESGCM(derived_key).decrypt(
            nonce, raw[offset + 28:], magic
        )
    except Exception:
        raise ValueError("Authentification AES-GCM impossible.") from None

    # Reuse the independent SQLite reconstruction/integrity verifier before
    # allowing any SQL from the artifact to reach the destination connection.
    with tempfile.TemporaryDirectory(prefix="chappie-restore-verify-") as work:
        verified_path = Path(work) / "snapshot.json"
        verified_path.write_bytes(plaintext)
        verified_path.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(plaintext).hexdigest()}  snapshot.json\\n",
            encoding="ascii",
        )
        verification = verify_logical_backup(verified_path)
    if not verification.get("valid"):
        raise ValueError(
            "Sauvegarde logique invalide : "
            + str(verification.get("reason", "contrôles d'intégrité échoués"))
        )
    try:
        payload = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Contenu de sauvegarde illisible.") from None
    report = restore_logical_backup_payload(
        connection,
        payload,
        target_identity=target_identity,
        expected_target_identity=expected_target_identity,
        production_identity=production_identity,
    )
    return {
        **report,
        "artifact_sha256": digest,
        "artifact_authenticated": True,
        "logical_integrity_verified": True,
    }
