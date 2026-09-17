request: hotfix/disable-legacy-integrations-enforcement-readiness
cycle: M
state: REVIEW
opened_at: 2026-09-17T10:20:00-03:00
last_update: 2026-09-17T10:42:08-03:00
agent_run_id: /root
current_blockers: []
next_action: "Obtain human review and green CI before merge; do not deploy or backfill from this gate."
artifacts_generated:
  - 00-context/production-diagnosis.md
  - 01-plan/master-plan.md
  - 03-verification/01-local-results.md
  - 05-deployment/01-rollout-and-rollback.md
  - HANDOFF.md
verification_runs: 5

watch_list:
  - apps/ai_agents/migrations/0009_disable_legacy_retry_schedule.py
  - apps/webhooks/n8n_inbound.py
  - apps/webhooks/n8n_outbox.py
  - apps/webhooks/tasks.py
  - apps/support/auto_assign_service.py
