# Dependency audit

## Confirmed legacy-only

- Heimdall classifiers, identity resolution/collection and the triage-first Supervisor.
- Django Ninja AI triage/Supervisor endpoints and the unmounted duplicate webhook router.
- HubSpot dispatch from AI-pipeline stages, `conversation.newMessage`, and
  `hs_last_message_from_visitor` into the Supervisor/Salomao pipelines.
- Celery message batching, waiting-message reconciliation, operational recovery,
  and retry branches that re-enter either legacy pipeline.
- AI-pipeline configuration, Heimdall thresholds, Supervisor rollout flags, and
  HubSpot subscriptions used only by those paths.

## Shared and preserved

- Durable `WebhookEvent` ingestion and the generic lifecycle/event/transition ledger.
- Matchmaker, support queues, assignment, agent availability/capacity/calendar,
  metrics, service cycles, and owner synchronization.
- Generic human handoff and audited provider-effect retry where independent.
- AI service, waiting, recovery, resolution, human and terminal lifecycle states.
- RAG, knowledge and HubSpot read tooling, and the standalone Salomao adapter when
  they do not expose or invoke legacy triage.
- Historical lifecycle, AgentRun and tool-audit rows.

## Runtime and data evidence

- Production API, worker and beat run the reviewed commit; the AI watchdog and
  lifecycle retry schedules are active.
- The last observed Heimdall/Supervisor runs and triage transitions were on
  2026-08-18. No current conversation is in a legacy triage state.
- Applied migrations and historical identity/triage metadata exist. This change
  therefore uses a forward migration and never deletes historical rows.
- The user explicitly authorized local implementation after this stop-gate was
  reported. No production mutation is authorized.

## Unrelated risks retained

- Supabase reports RLS disabled for four Help Desk calendar tables. This task
  does not change their policies.
- The remote database reports PostgreSQL 17.6.1 while repository documentation
  declares PostgreSQL 16.
