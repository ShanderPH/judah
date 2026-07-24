# OPS-07 — truthful PostgreSQL CI gate

Date: 2026-07-20
Scope: `.github/workflows/ci.yml` and destructive-test safety

## Implemented

- PostgreSQL remains pinned to `postgres:16-alpine`.
- Redis remains pinned to `redis:7-alpine` and is now also present in the
  Django checks job.
- The database name is unique per GitHub run and attempt:
  `judah_ci_${{ github.run_id }}_${{ github.run_attempt }}`.
- CI validates the redacted database identity before running migrations.
- Migrations run before pytest; migration failure stops the job.
- The test job runs the full pytest suite with coverage after migration.
- Django system checks now run after successful migration.

## Safety boundary

`common.database_safety` allows:

- a local SQLite file;
- local PostgreSQL on `localhost`, `127.0.0.1`, or `::1`;
- only `judah_test` locally or a `judah_ci_` database in CI;
- in GitHub Actions, only the exact database derived from the current
  `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT`.

Remote hosts, production-like names, missing URLs, unsupported backends, and
database names from another CI run fail before pytest setup. The assertion is
loaded from root `conftest.py`, so developers cannot bypass it by invoking
pytest directly.
