# PR 75 remediation — Gate B verification

Date: 2026-07-20
Verification window: 10:35–11:15 America/Sao_Paulo
Scope: BE-09, OPS-08, DB-03, BE-10; OPS-09 documentation only

## Environment identity

- PostgreSQL: `postgres:16-alpine`
- Host: `127.0.0.1`
- Port: `55432`
- Database: `judah_test`
- Redis: `redis:7-alpine` on `127.0.0.1:56379`
- Lifecycle: local Docker containers with `--rm`, stopped after verification

`common.database_safety` accepted the local disposable target before any
migration or test. No write, migration, role, credential, flag, or deployment
targeted staging, production, Supabase, Railway, or another shared service.

## Results

| Command / proof | Exit | Result |
|---|---:|---|
| `python -m common.database_safety` | 0 | local PostgreSQL identity accepted |
| `manage.py migrate --run-syncdb` | 0 | clean schema applied through `support.0016` |
| focused Gate B PostgreSQL tests | 0 | 12 passed |
| full PostgreSQL 16 suite | 0 | 411 passed |
| safe local SQLite suite | 0 | 410 passed, PostgreSQL-only test skipped |
| `ruff check .` | 0 | all checks passed |
| `ruff format --check .` | 0 | 246 files formatted |
| `mypy .` | 0 | no issues in 243 source files |
| `manage.py check --fail-level WARNING` | 0 | no issues |
| `makemigrations --check --dry-run` | 0 | no changes detected |
| `git diff --check` | 0 | clean |

## Acceptance proof

- With assignment disabled, duplicate webhook delivery creates one queue row
  and performs no SAT refresh or owner mutation.
- NOVO backlog reconciliation remains active with assignment disabled.
- Enabling assignment drains the preserved backlog.
- Railway pre-deploy migrations preserve pending and queued rows.
- Production without an explicit assignment switch is ingestion-only.
- Canary candidates are limited to configured local Agent UUIDs; invalid
  config and legacy eligibility both fail closed.
- Unauthorized Python count reconciliation returns before HubSpot or database
  mutation.
- PostgreSQL accepts the production runtime, schema migration, and break-glass
  roles; break-glass delete exercises the audited path.
- An arbitrary role remains rejected with SQLSTATE `42501` even after forging
  `application_name=judah:production:forged-client`.
- Migration reverse removes every trigger/function and reapply restores them.

## Gate decision

Gate B implementation and local PostgreSQL verification are complete.

OPS-09 shared-environment provisioning is intentionally not executed: role
creation/grants, staging isolation, credential rotation, migration, feature
flags, and deployment require Felipe's explicit approval. Gate C and later
workstreams remain out of scope until separately authorized.
