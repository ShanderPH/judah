# Master plan

## Scope

- **BE-01:** disable the exact persisted Celery Beat schedule for the removed lifecycle retry task.
- **BE-02:** add a fail-closed n8n delivery flag, default off, before dispatch, claim, or HTTP.
- **BE-03:** prevent enforced close writers from creating projections without an active cycle.
- **OPS-01:** after deploy, run verified dry-run and bounded persistent legacy-cycle backfill.
- **V-01:** verify schedule disabled, zero n8n HTTP attempts, zero legacy rows, readiness, and worker health.

## Safety and rollback

- Scheduler state is retained but disabled. Reverse migration intentionally never re-enables a task that does not exist.
- Disabled n8n delivery preserves outbox records and attempt counters; rollback is configuration-only after the endpoint is ready.
- No legacy record is deleted. The existing deterministic backfill creates auditable `legacy_backfill` cycles and is idempotent.
- Enforcement flags are not changed by this hotfix. Production activation remains gated on `enforcement_ready=true` after backfill.

## Acceptance criteria

- The obsolete task is no longer emitted after deploy.
- With delivery disabled, no n8n HTTP client call occurs and pending outbox state is unchanged.
- Enforced closure without an active cycle creates no null-cycle projection.
- CI, focused tests, Ruff, mypy, migration checks, and post-deploy readiness pass.
