# PR 75 remediation — Gate A verification

Date: 2026-07-20
Verification window: 08:50–09:20 America/Sao_Paulo
Scope: DB-02 and OPS-07 only

## Environment identity

- PostgreSQL: `postgres:16-alpine`
- Host: `127.0.0.1`
- Port: `55432`
- Database: `judah_test`
- Redis: `redis:7-alpine` on `127.0.0.1:56379`
- Lifecycle: local Docker containers with `--rm`
- Shared database check: read-only `django_migrations` query; `0015` and
  `0016` were absent

No test, migration, or write targeted staging, production, Supabase, or any
other shared database.

## Results

| Command / proof | Exit | Result |
|---|---:|---|
| `python -m common.database_safety` | 0 | local PostgreSQL identity accepted |
| `python manage.py migrate --run-syncdb` | 0 | clean schema applied through `support.0016` |
| targeted PostgreSQL migration and safety tests | 0 | 9 passed |
| `pytest` on PostgreSQL 16 | 0 | 402 passed in 36.85s |
| CI-equivalent pytest with coverage | 0 | 402 passed; 64.17% coverage |
| `ruff check .` | 0 | all checks passed |
| `ruff format --check .` | 0 | 245 files already formatted |
| `mypy .` | 0 | no issues in 242 source files |
| `manage.py check --fail-level WARNING` | 0 | no issues |
| `makemigrations --check --dry-run` | 0 | no changes detected |
| CI workflow YAML parse | 0 | valid YAML |
| `git diff --check` | 0 | clean |

## Iteration evidence

The first targeted migration test reused one `MigrationExecutor` across a
reverse/forward transition. Its loader retained stale applied-migration state,
so the test correctly failed before claiming the function existed. The test
was corrected to instantiate an executor for each transition and then passed
both targeted and full PostgreSQL runs.

## Gate decision

Gate A is ready for review:

- PostgreSQL 16 applies, reverses, and reapplies the migration;
- trigger rejection and allowed writes are integration-tested;
- CI provisions the required services and reaches the full suite;
- destructive tests fail before setup if the database target is not local and
  disposable.

Per the approved remediation plan, implementation stops before Gate B.
GitHub-hosted checks remain pending until the branch is intentionally
committed and pushed.
