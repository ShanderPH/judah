# Handoff — Native Heimdall Backend

## Outcome

The HubSpot Heimdall workflow now runs under JUDAH's native webhook, lifecycle,
identity, Supervisor, HubSpot-effect, audit, retry, and Matchmaker services. N8N
is not part of the runtime path.

## Main implementation

- Deterministic `CustomerIdentity` resolution from current-message delivery
  identifiers, CRM profiles, explicit customer data, and conversation memory.
- Identity lifecycle with bounded collection and human fallback.
- Verified-identity requirement for boleto, financial, and payment-method routes.
- Native Heimdall menu, typed output, confidence gates, critical-priority handoff,
  missing-data collection, and safe invalid-output behavior.
- Native dispatch no longer depends on `SALOMAO_V1_BASE_URL`.
- Database-backed business hours replace hard-coded workflow calendars.
- Idempotent, audited transition to the AI waiting stage after a successful reply.
- Identity status is included in human handoff notes without raw email or phone.
- N8N MCP placeholder and operational documentation references were removed.

## Operational rollout

1. Deploy with `AI_ROUTING_ENABLED=false`.
2. Validate HubSpot credentials, pipeline/stage IDs, sender actor, Redis, Celery,
   and the support calendar in staging.
3. Enable a small deterministic `AI_ROUTING_ROLLOUT_PERCENTAGE`.
4. Monitor identity outcomes, confidence clarifications, human handoffs, HubSpot
   errors, duplicate suppression, and Matchmaker queue health.
5. Increase the rollout only while the stop gates in `01-plan/master-plan.md`
   remain clear; disable `AI_ROUTING_ENABLED` for immediate rollback.

## Verification

- Full test suite on the current `main`: `1063 passed, 12 skipped`.
- Ruff: all selected application files passed.
- Mypy: no issues in the 10 changed runtime source files.
- Django system check: no issues.
- Migration drift: no changes detected.
- Git whitespace validation: passed.

The skipped tests are integration/migration cases guarded by environment-specific
capabilities. Tests used a disposable local SQLite database with `DJANGO_ENV=test`;
no production HubSpot, Redis, Celery, or customer data was changed.
