# Rollout and rollback

1. Deploy through reviewed PR and confirm `ai_agents.0009_disable_legacy_retry_schedule` applied.
2. Confirm the exact periodic task is `enabled=false` and no unregistered-task log recurs for two scheduling intervals.
3. Confirm `N8N_BOT_DELIVERY_ENABLED` is absent or false; verify no n8n HTTP attempt while new outbox rows remain pending.
4. Run `python manage.py backfill_conversation_cycles --dry-run --limit=500` and require JSON with zero ambiguous rows.
5. Run the same bounded command without `--dry-run`; verify `legacy_rows=0`, projection mismatches zero, and idempotent rerun.
6. Observe health, worker, Beat, assignment repairs, and closure logs before any enforcement/configuration change.

Rollback does not re-enable the obsolete Celery task. Keep n8n delivery off. Code rollback may restore prior close behavior, but
created legacy cycles and links are preserved because deleting audit history is unsafe. Any data reversal requires a separately
reviewed migration after proving no downstream references.
