# PR 75 — Gate F new-ticket-only boundary

Date: 2026-07-20

## Risk found before merge

The pre-deploy database contained three `new_conversations` rows:

- two `pending`;
- one `queued`;
- all three were ready for immediate reservation.

The existing durable drain selected every `pending`/`queued` row in FIFO order.
SAT eligibility transitions and the periodic drain could therefore assign the
pre-deploy backlog after enforcement was enabled.

## Persistent correction

Migration `support.0018_new_ticket_assignment_rollout_gate` adds
`automatic_assignment_eligible` with default `false`.

The invariant is:

> A queue row is considered by automatic assignment only when it was created
> by the canonical live webhook ingestion path under the new release.

Enforcement points:

- active queue counts filter `automatic_assignment_eligible=true`;
- both pre-lock and transaction-lock reservation queries filter the marker;
- no-candidate backoff filters the marker;
- NOVO reconciliation/backfill explicitly writes `false`;
- canonical live webhook creation explicitly writes `true`;
- an already active pre-deploy row is not promoted by a duplicate webhook.

## Local evidence

PostgreSQL local disposable database:

```text
Focused routing/lifecycle suite: 73 passed
Full repository suite: 430 passed
ruff check .: All checks passed
ruff format --check .: 255 files already formatted
mypy .: Success: no issues found in 252 source files
makemigrations --check --dry-run: No changes detected
git diff --check: clean
```

Regression coverage:

- migrated backlog cannot be reserved;
- live webhook ingestion opts a newly created row in;
- NOVO backfill remains excluded.

## Production pre-merge state

- Additive schema through `support.0017` is present.
- Nine writer triggers are installed in bootstrap transition mode.
- `judah_production_runtime` exists and is staged for API, Worker, and Beat.
- Automatic assignment is staged `true`; absence-safe enforcement is staged
  `true`.
- The old deployment remains healthy and no merge was performed by Codex.

Migration `support.0018` must be applied with all existing rows defaulted to
`false` before the new application release is promoted.
