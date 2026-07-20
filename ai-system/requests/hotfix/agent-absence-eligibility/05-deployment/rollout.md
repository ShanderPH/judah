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
7. deploy shadow with `AUTO_ASSIGNMENT_ENABLED=false`,
   `ABSENCE_SAFE_ELIGIBILITY_SHADOW=true`, and ingestion/reconciliation active;
8. validate one business day of decision telemetry and queue age/depth;
9. explicitly approve a canary with enforced eligibility, automatic assignment
   enabled, and `AUTO_ASSIGNMENT_CANARY_AGENT_IDS` set to local Agent UUIDs;
10. observe queue depth, heartbeat age, writer conflicts, and final-guard
   rejections.

Removing the canary allowlist or enabling full assignment requires a separate
explicit rollout action. No shared-environment credential, role, migration, or
feature-flag mutation is authorized by this document.

Nathan must remain `auto_assign_enabled=true`. His out-of-office interval makes
him ineligible today; after the interval ends, HubSpot availability, working
hours, and the 30-second stability window return him online automatically.
