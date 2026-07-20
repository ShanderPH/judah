# DB-03 / BE-10 — role-based writer isolation

`support.0016` now authorizes routing writes by PostgreSQL identity, not by
`application_name`.

Trusted roles:

- `judah_production_runtime`;
- `judah_schema_migration`;
- `judah_break_glass`.

The diagnostic `application_name` remains mandatory for trusted shared
identities but cannot elevate an untrusted role. Break-glass writes emit a
PostgreSQL server log. A narrowly scoped `postgres` exception exists only for
databases named `judah_test*`/`test_judah_test*` with the exact
`judah:local-test:pytest` application name.

The trigger covers `INSERT`, `UPDATE`, and `DELETE` on `agents`, plus queue,
assignment, assignment log, status history, availability decision, lease, and
reassignment tables. The future durable-attempt migration must install the
same guard on its new table.

Python defense in depth now rejects non-authoritative SAT/load/count writers,
lifecycle repairs, queue mutations, Django Admin changes, and manual assignment
entrypoints before network or database mutation.

Shared-environment roles, grants, credentials, and rotation remain an OPS-09
prerequisite requiring Felipe's explicit approval.
