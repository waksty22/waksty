# Turso logical restore — safe implementation plan

## Status

Design only. This document does not enable writes, change deployment settings, or connect to a database.

## Existing building blocks

- `storage.logical_backup.verify_encrypted_logical_backup()` authenticates the AES-256-GCM artifact, checks its SHA-256 sidecar, decrypts into a private temporary directory, and validates the logical snapshot by rebuilding it in an isolated SQLite database.
- The logical format is versioned (`chappie-turso-logical-backup`, version 1) and carries table definitions, rows, indexes, views, triggers, and row-count summaries.
- `storage.hrana_http.HranaHttpTransaction` intentionally permits only single `SELECT` statements plus transaction control. Keep this client read-only.
- `storage.data_migration.migrate_sqlite_rows_to_turso()` is a separate SQLite-to-Turso migration path. It has an explicit `apply=True` gate, schema planning, collision checks, row verification, foreign-key checks, and a migration marker. It is not a drop-in restore API: its source assumptions and marker semantics describe a migration, not restoration from a portable backup.

## Proposed restore architecture

Implement a separate, explicitly write-capable restore path. It must not weaken or reuse the read-only backup transport.

1. **Artifact preflight (offline):** accept an explicit archive path and key supplied by the operator; reject path traversal, duplicate ZIP entries, unexpected files, oversized archives, malformed checksum sidecars, unsupported format versions, invalid identifiers, and invalid SQL object ordering. Authenticate and verify the encrypted artifact before opening any target connection.
2. **Isolated staging:** decrypt only inside a private temporary directory; rebuild the snapshot in a temporary SQLite database; run `integrity_check`, `foreign_key_check`, exact table/object inventory checks, and row-count checks. Never log row values, credentials, or encryption material.
3. **Explicit target identity:** require a separately supplied target URL and token. Never read the production target implicitly from the app's default environment. Require an explicit operator acknowledgement of the target identity (safe database hostname/name only; never print tokens).
4. **Fail-closed target preflight:** inspect target metadata and counts. Default policy is an empty, dedicated restore target only. Reject any user tables or rows unless a future separately reviewed merge mode is designed. Do not auto-create databases or alter provider settings.
5. **Schema and data apply:** use a dedicated write-capable Hrana transport with parameterized inserts and a strict allowlist of transaction-control statements. Create schema objects in dependency-safe order; insert rows in batches; rebuild indexes/views/triggers after rows where required. Handle foreign-key dependencies explicitly; never disable checks merely to force a restore.
6. **Atomicity and uncertain outcomes:** perform all target changes in one transaction where supported. If the transport loses its baton or the commit response is ambiguous, stop and mark the run as outcome-unknown; do not retry blindly. Provide a read-only reconciliation command to inspect target counts and a restore-run marker before any retry.
7. **Post-restore verification:** compare exact table/object inventories, per-table row counts, stable per-table content digests, `integrity_check`, and `foreign_key_check`. Commit only after all checks pass. Report counts and hashes only, never row contents.
8. **Auditability:** record a restore-run ID, source artifact SHA-256, target identity fingerprint, format version, counts, timestamps, and verification outcome. Do not store credentials or encryption keys in the database or logs.

## Required tests before considering implementation complete

- valid encrypted archive; wrong key; tampered ciphertext; missing/mismatched sidecar; malformed JSON; unsupported format version;
- ZIP path traversal, duplicate entries, unexpected entries, archive size limits;
- empty target accepted; non-empty target rejected without writes;
- schema mismatch and unsupported virtual/generated objects rejected;
- BLOB, NULL, integer, float, Unicode, and duplicate rows preserved;
- failure during schema creation, mid-batch insertion, FK check, and pre-commit verification rolls back all target changes;
- simulated lost connection during COMMIT yields an explicit unknown outcome and never triggers an automatic retry;
- successful restore can be reopened through a new connection and matches source inventories, row counts, and digests;
- all integration tests use temporary SQLite or a dedicated disposable Turso database, never production.

## Operator rollout gates

1. Merge the design and implementation only after review and CI.
2. Create a dedicated disposable Turso database manually; do not point tests at `chappie-db`.
3. Configure its credentials through the approved secret manager (never paste secrets into chat or source control).
4. Run a dry-run/preflight and verify the target identity.
5. Restore and verify a backup in that isolated database.
6. Document a human-reviewed recovery procedure before any production recovery is attempted.

## Explicit non-goals

- No production restore, migration, reset, deletion, truncation, or schema change.
- No automatic database provisioning, secret creation, or Render/GitHub environment mutation.
- No change to the existing read-only backup client.
- No claim of disaster-recovery readiness until a real isolated Turso restore has passed end to end.
