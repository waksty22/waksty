# V50.46 — Cognitive state reconstruction after restart

## Objective
Prove that persisted cognitive records can be reconstructed by a fresh database
connection, and that pending post-commit work remains available after close/reopen.

## Tests
- Persist vocabulary, sensory observation, affective snapshot and a conversation;
  close the connection; reopen; rebuild the actual shared-brain snapshot and
  formatted context; compare the persisted cognitive sections.
- Verify pending finalization outbox jobs survive close/reopen, retain failure
  details and can be marked completed on retry.
- Verify the shared snapshot remains user-scoped after restart.
- Verify replaying a stable learning event after restart does not duplicate it.

## Boundaries
All tests use isolated temporary SQLite files and production repository read/write
functions. They do not launch Render, connect to Turso, call Gemini, read secrets,
or alter production data. A local close/reopen test models connection/process
state reconstruction; it does not prove that Render's ephemeral filesystem is
durable, nor that the current Turso adapter has equivalent semantics.
