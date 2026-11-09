# V50.45 — Cognitive effects atomicity and idempotency

## Scope
This increment adds integration tests around the real cognitive side-effect
functions used by classic chat and Gemini Live. It does not change runtime
behavior or enable Turso.

## Covered invariants
- Affective snapshots are recorded once per user/event/effect.
- Heard vocabulary is idempotent and remains at the `heard` stage.
- Explicit word teaching replay does not increment exposure a second time.
- Replaying a sensory event returns the original observation.
- Equal content from distinct event IDs remains distinct experience.
- Receipt rows and cognitive effects roll back together; retry after rollback
  can persist the complete event.
- Event receipts are scoped by user and effect kind.

## Isolation and limitations
Tests use a temporary SQLite database and call the actual repository
functions. They do not contact Render, Turso, Gemini, GitHub secrets, or the
production database. They verify local SQLite transaction semantics only;
they do not establish libSQL/Turso transaction compatibility or durable
production persistence. The Live WebSocket and provider transport are not
started by these tests.
