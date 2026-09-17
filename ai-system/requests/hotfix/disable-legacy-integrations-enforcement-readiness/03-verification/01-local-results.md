# Local verification

## RED

The new regression tests failed before production changes for:

- persisted legacy schedule repair;
- disabled n8n delivery still claiming/calling transport;
- disabled poller still dispatching;
- enforced close still creating a null-cycle closed projection.

Unrelated cycle tests initially failed because the local command omitted `DJANGO_ENV=test`; reruns use the repository's explicit
test authority fence.

## GREEN

- 40 focused tests passed after the first implementation pass.
- 62 final focused/regression tests passed, including the existing deterministic backfill suite.
- Ruff passed on every modified Python file.
- mypy passed on the modified production modules.
- `makemigrations --check --dry-run` passed with no missing migration.
- The n8n gate is covered before broker dispatch, outbox claim, and HTTP.

## Operational evidence

- Production had one enabled obsolete schedule matching the removed task.
- Production had 195 null-cycle closed rows, all after migration 0020 and with no existing candidate cycle.
- Production n8n posture was configured but not required; observed outbox counts included 13760 dead letters and 459 retries.
- No persistent backfill, flag change, or production configuration mutation was performed during implementation.
