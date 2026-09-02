## Summary

- Reuse and lock the persisted HubSpot webhook envelope during hydration instead
  of attempting a duplicate ledger insert.
- Use conflict-safe insertion for webhook retries and reconciliation paths where
  the ledger row may legitimately not exist.
- Preserve terminal states when a provider failure races with successful
  reconciliation.

## Root cause

`record_hubspot_message_envelope()` persisted the canonical ledger row before
dispatching hydration. `ingest_hubspot_message()` then unconditionally attempted
another insert with the same `deduplication_key` and recovered from PostgreSQL
`23505`. The savepoint made the behavior functionally idempotent, but normal
traffic appeared as database failures and degraded Supabase telemetry.

## Implementation

- Hydration passes the existing event UUID into canonical ingestion.
- Canonical ingestion locks that exact row and validates its canonical key.
- Callers without an envelope use `ON CONFLICT DO NOTHING` semantics before
  selecting the canonical row with `FOR UPDATE`.
- Ledger completion and outbox creation remain in the same transaction.
- Unique constraints on ledger and outbox remain unchanged.

## Concurrency and idempotency

- Two hydrations serialize on the same `WebhookEvent` row.
- Hydration and reconciliation converge on the same row and at most one outbox.
- `READY` and `IGNORED` remain idempotent terminal no-ops.
- `RECEIVED` and `ERROR` remain recoverable.
- A canonical-key mismatch fails closed without mutating the envelope.

## Validation

- PostgreSQL 16 full suite: **796 passed, 4 skipped**, 90.71% coverage.
- SQLite full suite: **769 passed, 31 skipped**, 90.48% coverage.
- All five PostgreSQL-only webhook contention tests passed.
- PostgreSQL logs contained zero `23505` matches for the `webhook_events`
  deduplication constraint during the suite.
- Ruff check and format checks passed.
- Django system checks, migrations, and `makemigrations --check` passed.
- All pre-commit hooks passed for every commit.

Mypy 2.1.0 remains unavailable because `NewSemanalDjangoPlugin` fails during
plugin construction, before source analysis. This is the repository's existing
tooling blocker and is recorded in the verification artifact.

## Risk and rollout

- Low code blast radius: two production files, no schema or external contract
  changes.
- Deploy worker first, then API, and align Beat to the same SHA without changing
  schedules or flags.
- Compare pre/post-deploy `23505`, ledger states, outbox cardinality, lock waits,
  and latency.

## Rollback

Redeploy the previous SHA if messages are lost, `READY` rows lack outboxes,
terminal states regress, lock timeouts/deadlocks repeat, or p95 latency exceeds
twice the baseline. No data or schema rollback is required.

## Out of scope

- n8n workflow activation or configuration.
- Recovery or replay of the independent HTTP 404 / `DEAD_LETTER` backlog.
- Schema changes or removal of unique constraints.
- Opportunistic refactors.

## Checklist

- [x] Minimal production patch
- [x] PostgreSQL concurrency coverage
- [x] Retry and rollback regression coverage
- [x] One ledger and at most one outbox per message
- [x] No normal hydration insert or `23505`
- [x] No migration
- [x] Deployment and rollback plan documented
