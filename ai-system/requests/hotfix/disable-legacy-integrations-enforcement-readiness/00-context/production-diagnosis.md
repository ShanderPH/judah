# Production diagnosis

Evidence captured on 2026-09-17 after PR 120 deployed:

- `ai-lifecycle-retry-dispatch` remained enabled in `django_celery_beat_periodictask` even though
  `ai_agents.retry_failed_lifecycle_instances_task` no longer exists. Beat emitted it every minute and workers discarded it.
- n8n delivery credentials and URL are configured, but delivery is not an approved active integration. Production accumulated
  `13760` dead letters and the observed endpoint returned HTTP 404. Outbox data must remain durable while HTTP is disabled.
- `195` closed-conversation projections had no cycle. All were created after migration `support.0020`; none had an existing
  unclaimed cycle candidate. Deleting them or attaching them to an existing cycle would destroy or invent audit history.
- The existing `backfill_conversation_cycles` command can create deterministic `legacy_backfill` cycles without external calls.
  The close writer still allowed a null cycle under enforcement and must fail closed before that backfill is persisted.

No production data was mutated during diagnosis. A dry-run was invoked but Railway returned no report, so it is not accepted as
verification evidence.
