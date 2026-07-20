# Deployment and enforcement gate

No production deployment or mutation was performed in this run.

Required approved sequence:

1. authenticate/provide Railway access;
2. confirm staging and production service/environment identities;
3. give staging isolated PostgreSQL and Redis credentials;
4. create separate `judah_production_runtime`, `judah_schema_migration`, and
   `judah_break_glass` PostgreSQL roles with least-privilege grants;
5. rotate production credentials if prior sharing cannot be disproved, and
   set a unique `application_name` per Railway service;
6. apply migrations `support.0015` and `support.0016` using only the schema
   migration identity;
7. Felipe's 2026-07-20 Gate F approval selects direct enforced assignment:
   `AUTO_ASSIGNMENT_ENABLED=true`,
   `ABSENCE_SAFE_ELIGIBILITY_SHADOW=false`, and
   `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=true`;
8. migration `support.0018` keeps every pre-deploy/backfilled queue row
   `automatic_assignment_eligible=false`;
9. only the canonical live webhook ingestion path may create a queue row with
   `automatic_assignment_eligible=true`;
10. observe queue depth, heartbeat age, writer conflicts, final-guard
    rejections, and prove that the pre-deploy backlog has zero assignment
    attempts.

Felipe explicitly authorized the production roles, migrations, feature flags,
and direct enforcement on 2026-07-20. Felipe retains sole responsibility for
merging PR 75. Codex must not merge the pull request.

Nathan must remain `auto_assign_enabled=true`. His out-of-office interval makes
him ineligible today; after the interval ends, HubSpot availability, working
hours, and the 30-second stability window return him online automatically.
