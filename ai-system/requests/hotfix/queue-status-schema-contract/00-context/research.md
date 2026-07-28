# Research — Supabase queue-status error storm

## Incident scope

- Environment: production `HelpdeskDB` (`vmvjddgjyunywbfcbbig`).
- Observation window: 2026-07-28 10:10–11:10 BRT, with recurrence
  reconfirmed at 11:17:22 BRT.
- Read-only evidence sources: Supabase PostgreSQL/API logs, live catalog and
  persisted queue/cycle/attempt aggregates, repository documentation, Django
  migrations and current code at base SHA
  `40fe5089db3be413071f0282b3b4680395474a76`.
- No database mutation, queue cleanup, replay, flag change, deploy or external
  owner mutation was performed during diagnosis.

## Confirmed symptoms

1. The 60-minute sample contained 73 PostgreSQL errors:
   - 68 violations of `new_conversations_queue_status_check`;
   - 5 violations of `conversation_instances_idempotency_key_key`.
2. Supabase API logs contained no 4xx/5xx response in the same sample.
3. The queue-status violation recurs on the 60-second Celery Beat cadence and
   also appears in event-driven bursts.
4. Supabase remained `ACTIVE_HEALTHY`; performance advisors reported only
   pre-existing `INFO`/`WARN` lints and no critical capacity finding.

## Root cause A — production schema drift

The application contract defines `NewConversation.QueueStatus.FAILED =
"failed"`. The durable assignment protocol writes this state when it must
quarantine a stale cycle, an ambiguous legacy row or a permanent provider
failure.

The live PostgreSQL constraint is still:

```sql
CHECK (queue_status = ANY (ARRAY['pending', 'queued']))
```

The constraint originated in Supabase migration
`20260406143701_add_queue_fields_to_new_conversations`, which explicitly added
the column with `CHECK (queue_status IN ('pending', 'queued'))`.

Django migration `support.0014_newconversation_failure_tracking` added the
`failed` choice and is recorded as applied in production, but changing
`CharField.choices` is not database DDL in Django 5.2. Consequently, it could
not alter a CHECK constraint created independently by Supabase SQL.

## Persisted impact

At diagnosis time `new_conversations` contained eight active rows:

- 8/8 were eligible for automatic assignment;
- 8/8 had no `cycle_id`;
- 8/8 had a historical completed assignment attempt;
- 8/8 therefore entered the `legacy_cycle_ambiguous` quarantine path;
- the oldest had waited approximately 26 hours;
- three had an open local assigned projection;
- seven had closed history;
- five had no open local assigned projection, but their authoritative HubSpot
  owner was not verified in this read-only investigation.

The quarantine write is rejected. Its transaction rolls back, leaving the row
active. The 60-second drain selects it again and aborts before processing later
rows. This creates persistent head-of-line blocking and error amplification.

## Contributing conditions

- `CONVERSATION_CYCLES_ENFORCED=false` intentionally preserves a legacy writer
  path when cycle admission cannot be attached. It is not the primary defect
  and must not be enabled as an emergency workaround.
- Local Django-created test schemas do not reproduce the Supabase-authored
  CHECK constraint, so application tests can pass while production rejects the
  state.
- `docs/database/models.md` still documents `queue_status` as only
  `pending / queued`.
- The assignment-resilience plan assumed the existing `queue_status` contract
  required no migration; the live CHECK definition was not part of that gate.

## Root cause B — noisy lifecycle race

`LifecycleEngine.record_normalized_event()` opens an outer
`transaction.atomic()`. `_get_or_create_instance()` attempts a direct INSERT,
catches `IntegrityError`, then queries again without an inner atomic savepoint.
Django documents that catching a database exception inside an atomic block can
leave the transaction broken until rollback.

The five sampled UNIQUE violations aligned within 0.4 seconds of processed
HubSpot property webhooks. All five webhooks were `processed=true`, had no
retry/error persisted and had matching lifecycle events, so no definitive event
loss was observed. The current pattern is nevertheless noisy and unsafe under
concurrency and can exercise the deterministic fallback redundantly.

## Safety boundary for the hotfix

- Fix the schema contract before allowing queue convergence.
- Preserve queue rows, attempts, cycles, logs and assignment history.
- Never replay or reassign rows that may already have an authoritative owner.
- Verify HubSpot ownership before any targeted replay/recovery.
- Keep cycle enforcement disabled until its separately authorized legacy
  reconciliation is complete.
