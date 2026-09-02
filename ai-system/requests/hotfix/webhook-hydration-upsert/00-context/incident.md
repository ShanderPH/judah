# Incident context

- Production SHA at investigation time: `27fcd109a193cf19a21ab78d77c29dd0c612533a`.
- `conversation.newMessage` first persists a `WebhookEvent` envelope and then
  hydrates it asynchronously.
- The canonical ingestion service attempted a second insert with the same
  `deduplication_key`; PostgreSQL `23505` was caught and used to recover the
  original row.
- Persistent cardinality was healthy, but expected exceptions polluted database
  telemetry and the Supabase success-rate signal.
- The independent n8n HTTP 404 / `DEAD_LETTER` backlog is explicitly out of
  scope.

## Invariants

- Keep unique constraints on ledger and outbox.
- At most one ledger and one outbox per canonical message.
- Preserve `RECEIVED`, `ERROR`, `READY`, and `IGNORED` recovery semantics.
- Ledger completion and outbox creation remain in one transaction.
- No schema, n8n, feature-flag, or backlog changes.
