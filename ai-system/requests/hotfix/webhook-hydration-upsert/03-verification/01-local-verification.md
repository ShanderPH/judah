# Local verification

## Passed

- Branch created from `27fcd109a193cf19a21ab78d77c29dd0c612533a`.
- `uv run ruff check` passed for all five changed Python files.
- `uv run ruff format --check` passed for all five changed Python files.
- `git diff --check` passed for the scoped implementation.
- `uv run python run_checks.py` passed: clean migrations and Django system
  checks.
- Full local SQLite suite after the final patch: 769 passed, 31 skipped,
  90.48% coverage.
- Full PostgreSQL 16 suite: 796 passed, 4 skipped, 90.71% coverage.
- All five PostgreSQL-only webhook contention tests passed, including two
  simultaneous hydrations and hydration versus reconciliation.
- PostgreSQL logs used SQLSTATE in `log_line_prefix`: the full suite emitted 27
  intentional `23505` errors for unrelated constraint tests and zero matches for
  the `webhook_events` deduplication constraint.
- Unit regressions prove no ledger insert during normal envelope hydration,
  conflict-safe retry SQL, transactional rollback on outbox failure, canonical
  key validation, and terminal-state preservation.

## Tooling blocker

- `uv run mypy apps/webhooks/n8n_inbound.py apps/webhooks/reconciliation.py`
  stopped before source analysis with the existing mypy 2.1.0 plugin error:
  `Error constructing plugin instance of NewSemanalDjangoPlugin`.

Only the local Docker Desktop and disposable `judah_test` PostgreSQL target were
used. No merge, deploy, production mutation, n8n change, or dead-letter recovery
was performed during verification.
