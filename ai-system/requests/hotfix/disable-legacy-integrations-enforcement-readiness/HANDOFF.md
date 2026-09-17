# Handoff

## Implemented

- Disabled the persisted removed-task schedule through a narrowly scoped data migration.
- Added a default-off n8n delivery gate before broker dispatch, outbox claim, and HTTP.
- Made enforced ticket closure fail closed when no active conversation cycle exists.
- Preserved all outbox and legacy conversation data; production backfill remains a post-deploy gate.

## Modified files

- `apps/ai_agents/migrations/0009_disable_legacy_retry_schedule.py`
- `apps/ai_agents/tests/test_legacy_removal.py`
- `apps/webhooks/n8n_inbound.py`
- `apps/webhooks/n8n_outbox.py`
- `apps/webhooks/tasks.py`
- `apps/webhooks/tests/test_n8n_inbound.py`
- `apps/webhooks/tests/test_n8n_outbox.py`
- `apps/webhooks/tests/test_tasks.py`
- `apps/support/auto_assign_service.py`
- `apps/support/tests/test_cycle_dual_write.py`
- `core/settings/base.py`
- `core/settings/production.py`
- `core/settings/test.py`

## Critical verification order

1. Migration disables only the obsolete schedule and wakes DatabaseScheduler.
2. n8n HTTP cannot occur while delivery is disabled; outbox stays durable.
3. Close events cannot recreate null-cycle rows under enforcement.
4. Dry-run report must show zero ambiguity before persistent backfill.

## Known risks

- Existing dead-letter/retry rows are preserved and need a separate disposition before future n8n activation.
- Missing-cycle close events fail closed and are logged; operators must repair identity rather than invent a cycle.
- Production backfill and any configuration change are not part of the code commit/deploy automatically.
