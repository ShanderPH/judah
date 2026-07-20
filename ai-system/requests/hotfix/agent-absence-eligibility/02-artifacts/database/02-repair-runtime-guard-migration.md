# DB-02 — repair routing writer migration

Date: 2026-07-20
Scope: `support.0016_block_non_authoritative_runtime_writes`

## Decision

A read-only query against the shared HelpdeskDB `django_migrations` table
returned no rows for `support.0015_absence_safe_eligibility` or
`support.0016_block_non_authoritative_runtime_writes`. Therefore `0016` was
safe to repair in place; no applied migration history was rewritten.

The PL/pgSQL `RAISE EXCEPTION` placeholder is now written as `%%` in the
Python string passed through Django's schema editor. Psycopg receives it as a
literal percent marker, while PostgreSQL still receives the single `%`
required by `RAISE`.

## PostgreSQL proof

`test_runtime_guard_migration.py` runs only on PostgreSQL and proves:

- reverse from `0016` to `0014` removes the guard function and every trigger;
- forward migration applies `0015` and `0016`;
- a production-labelled runtime can mutate guarded routing state;
- a staging-labelled runtime receives SQLSTATE `42501`;
- the rejected update does not change the agent row;
- a second reverse and reapply succeeds.

The test recreates `MigrationExecutor` after each graph transition so applied
migration state is never inferred from a stale loader snapshot.
