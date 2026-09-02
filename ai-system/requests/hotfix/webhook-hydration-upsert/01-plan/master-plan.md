# Master plan

## BE-01 — Reuse the persisted envelope

Pass the envelope UUID from `hydrate_webhook_message_event()` to
`ingest_hubspot_message()`. Inside the existing atomic block, lock that exact
row and reject a canonical-key mismatch.

## BE-02 — Replace exception-driven insertion

For callers that may not have an envelope, use a single-row Django bulk insert
with conflict ignored, then select the canonical row with `FOR UPDATE`. Apply
the same insert-if-absent behavior to webhook envelope retries.

## BE-03 — Preserve terminal states under provider failure

Make hydration failure recording conditional so it cannot overwrite a
concurrent `READY` or `IGNORED` result.

## V-01 — Verification

- Unit/regression tests for hydration, retries, rollback, mismatch, and terminal
  state preservation.
- PostgreSQL 16 contention tests for two hydrations and hydration versus
  reconciliation.
- Prove the normal hydration path issues no ledger insert and the fallback path
  uses `ON CONFLICT`.
- Run Ruff, mypy, migration checks, full suite, and PostgreSQL log inspection
  for SQLSTATE `23505`.

## Acceptance criteria

- One ledger row and at most one outbox per canonical message.
- Normal envelope hydration performs no second ledger insert.
- Concurrent creation does not surface `IntegrityError`.
- No schema or external contract changes.
