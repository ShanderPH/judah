# Absence-safe assignment operations

## Authority model

HubSpot Users API `2026-03` is the only remote authority for automatic agent
availability. JUDAH evaluates these properties together:

- `hs_availability_status`;
- `hs_out_of_office_hours`;
- `hs_working_hours`;
- `hs_standard_time_zone`;
- the account-scoped User `hs_object_id`.

`status_enum` is an operational projection, not an independent source of
truth. Editing it directly cannot create eligibility because the Matchmaker
also requires a fresh `eligibility_state=eligible` snapshot and revalidates it
under a row lock.

The Django Admin and support API expose availability fields as read-only.
Exceptional direct database edits remain possible for authorized operators,
but the next HubSpot reconciliation will restore the authoritative state.

Before reserving capacity for an enforced assignment, the Matchmaker reads the
selected HubSpot user by ID without using the SAT cache. This read-only veto
rejects `away`, active out-of-office, outside working hours, malformed data,
and failed or missing responses. Continuous SAT reconciliation remains the
only writer of availability snapshots and revisions.

## Environment isolation

Only the environment named by `AVAILABILITY_AUTHORITY_ENVIRONMENT` may run SAT
or automatic assignment. The default authority is `production`.

The runtime guard compares both:

- `DJANGO_ENV`;
- Railway's injected `RAILWAY_ENVIRONMENT_NAME`.

This prevents a Docker default or an incorrectly shared `DATABASE_URL` from
turning staging into an authoritative writer.

PostgreSQL provides a second fence. JUDAH connections set:

```text
application_name=judah:<environment>:<service>
```

Migration `support.0016_block_non_authoritative_runtime_writes` rejects
staging/development/test/preview mutations to availability, capacity, leases,
queue rows, assignments, and assignment audit rows.

Staging should still use a separate database and Redis instance. The triggers
are defense in depth, not a reason to keep shared credentials.

## Reconciliation behavior

The SAT heartbeat:

1. rejects non-authoritative runtimes before any HubSpot or database action;
2. acquires a token-owned database lease with a 25-second TTL;
3. reads the versioned HubSpot Users API;
4. normalizes availability, absence, schedule, and timezone;
5. locks agents in deterministic order;
6. rejects stale fencing generations;
7. persists the observation, reason, writer identity, task ID, state hash, and
   monotonic revision atomically;
8. releases the lease only when the stored token still belongs to the task.

Unavailable signals demote immediately. Promotion requires two consistent
samples and at least 30 seconds of stability. A persisted observation older
than 60 seconds cannot pass the final assignment guard.

When an out-of-office interval ends, an otherwise available agent becomes
eligible automatically after the stability window. Do not toggle
`auto_assign_enabled` for ordinary absence.

## Feature flags

| Variable | Safe rollout value | Purpose |
|---|---|---|
| `AUTO_ASSIGNMENT_ENABLED` | `true` | Global emergency kill switch |
| `AVAILABILITY_AUTHORITY_ENVIRONMENT` | `production` | Names the sole writer environment |
| `ABSENCE_SAFE_ELIGIBILITY_SHADOW` | `true` | Computes/audits decisions without changing routing |
| `ABSENCE_SAFE_ELIGIBILITY_ENFORCED` | `false`, then `true` after validation | Enforces absence-safe status and Matchmaker filtering |
| `AVAILABILITY_FRESHNESS_SECONDS` | `60` | Maximum observation age |
| `AVAILABILITY_REQUIRED_SAMPLES` | `2` | Required consistent available samples |
| `AVAILABILITY_STABLE_SECONDS` | `30` | Required stable available duration |
| `AVAILABILITY_LEASE_TTL_SECONDS` | `25` | Singleton reconciliation lease |

## Controlled rollout

1. Deploy migrations `0015` and `0016` before API/Worker/Beat startup.
2. Keep `ABSENCE_SAFE_ELIGIBILITY_SHADOW=true` and
   `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=false`.
3. Confirm `/api/v1/health/ready` reports:
   - production: `authoritative_writer=true`;
   - staging: `authoritative_writer=false`.
4. Observe one complete business day of `agent_availability_decisions`.
5. Investigate every legacy-online/new-ineligible difference, especially
   `malformed_remote_data`, missing identities, and missing working hours.
6. Enable `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=true` for a canary subgroup/window.
7. Expand enforcement after observing queue depth, final-guard rejections, and
   heartbeat freshness.

Changing Railway variables, applying production migrations, or enabling final
enforcement requires explicit approval.

## Railway inspection

The local CLI must be authenticated before use:

```powershell
railway.cmd login
railway.cmd status --json
railway.cmd deployment list --environment staging --json
railway.cmd logs --environment staging --service Worker
railway.cmd logs --environment production --service Worker
```

Never print variable values into logs. Compare only the relevant key presence
and resource references. Staging must not reference the production
`DATABASE_URL` or production Redis resource.

## Verification queries

Writer attribution:

```sql
select
    writer_id,
    runtime_environment,
    eligibility_reason,
    count(*)
from agent_availability_decisions
where created_at >= now() - interval '10 minutes'
group by 1, 2, 3
order by 4 desc;
```

Stale availability:

```sql
select id, name, eligibility_state, eligibility_reason,
       availability_observed_at, availability_writer_id
from agents
where is_active is not false
  and (
    availability_observed_at is null
    or availability_observed_at < now() - interval '60 seconds'
  );
```

## Rollback

Rollback must not restore fail-open routing:

1. set `AUTO_ASSIGNMENT_ENABLED=false`;
2. keep staging/runtime database guards installed;
3. keep conversations queued;
4. investigate/repair HubSpot parsing or identity mapping;
5. restore shadow mode;
6. re-enable global assignment only after fresh eligibility is healthy.

## Conversation cycles and reopened tickets

A HubSpot ticket may have multiple sequential support cycles. The durable
identity is the account, ticket and proven NOVO-stage entry timestamp; retries
of the same occurrence reuse the cycle, while a legitimate entry after closure
opens another cycle. Queue, assignment, closure, attempts, logs and
reassignments must carry the same `cycle_id`.

Before enabling `CONVERSATION_CYCLES_ENFORCED`, verify that API, Worker and Beat
run cycle-aware code and that readiness reports no legacy writers. Never use
receipt time or `timezone.now()` to manufacture a missing stage occurrence.

### Backfill procedure

The backfill never calls HubSpot or changes ticket owners by default. On a
staging clone or other explicitly authorized database:

```powershell
uv run python manage.py backfill_conversation_cycles --dry-run --limit 500 --report gate-e-dry-run.json
uv run python manage.py backfill_conversation_cycles --after <last-ticket-id> --limit 500 --report gate-e-batch.json
```

Review every quarantined row before continuing. A batch is resumable from
`next_cursor`; reexecuting it must not create another cycle or repeat a link.
Use `--ticket` for an individually approved investigation. External HubSpot
evidence and incident-ticket repair require separate authorization.

### Cycle verification queries

More than one active cycle is an invariant violation:

```sql
select source_account_id, hubspot_ticket_id, count(*)
from support_conversation_cycles
where state in ('queued', 'assigned', 'repair_required')
group by 1, 2
having count(*) > 1;
```

Coverage must be reviewed per table before enforcement:

```sql
select 'new_conversations' as source, count(*) filter (where cycle_id is null) as missing from new_conversations
union all
select 'assigned_conversations', count(*) filter (where cycle_id is null) from assigned_conversations
union all
select 'closed_conversations', count(*) filter (where cycle_id is null) from closed_conversations
union all
select 'assignment_attempts', count(*) filter (where cycle_id is null) from assignment_attempts
union all
select 'assignment_logs', count(*) filter (where cycle_id is null) from assignment_logs
union all
select 'conversation_reassignments', count(*) filter (where cycle_id is null) from conversation_reassignments;
```

Rollback is functional and non-destructive: disable enforcement or automatic
assignment, retain cycle data and reconciliation, and repair ambiguities. Do
not reverse migration `0023` after multi-cycle rows exist; its guard refuses to
recreate ticket-wide uniqueness over valid history.

### Cycle rollout readiness

Both `/api/v1/health/ready` and the support queue health response expose a
PII-free `conversation_cycles` posture. Before requesting enforcement, require:

- `portal_configured=true` and `migration_applied=true`;
- `legacy_rows=0` and `legacy_writers_detected=false`;
- `projection_mismatches=0`;
- `queued_without_dispatch=0`;
- `enforcement_ready=true`.

`cycles_by_state` is an aggregate observation surface. Any increase in legacy
rows after deploy means an old or non-cycle-aware writer remains active: stop
the rollout, drain the old process and keep enforcement off. A queued cycle
without dispatch must be recovered before proceeding.

Enforcement must not be used as a probe. Set
`CONVERSATION_CYCLES_ENFORCED=true` only after the readiness contract is already
green and the specific canary/enforcement approval has been recorded.

## Resilient queue recovery

Use the following order for an assignment incident. All commands in the first
stage are read-only; do not drain or repair until the aggregate baseline has
been reviewed.

```powershell
railway.cmd whoami
railway.cmd status --json
railway.cmd logs --service API
railway.cmd logs --service Celery-Worker
uv run python manage.py profile_legacy_cycles
uv run python manage.py backfill_conversation_cycles --dry-run --limit 100 --report cycle-dry-run.json
```

Readiness must account for `ready_queue_depth`, `oldest_ready_age_seconds`,
`poisoned_queue_rows`, `completed_attempt_queue_conflicts`, `expired_claims`
and `conversation_cycles.queued_without_dispatch`. A poisoned row degrades the
component but is isolated; a missing durable migration, unavailable database,
or stuck durable attempt is unhealthy and stops owner effects.

For an individually approved recovery, classify the row before processing:

- completed attempt for the same cycle: consume the residual queue projection
  as `converged_completed`, without another HubSpot owner call;
- legacy row without proven cycle identity: quarantine with
  `legacy_cycle_ambiguous`; never invent an entry timestamp;
- owner already present in HubSpot: converge the local queue/cycle as
  `hubspot_manual`, without overwriting the owner;
- transient provider failure: retain the row with a bounded retry timestamp;
- permanent item failure: quarantine only that row and continue the drain.

Stop immediately if `assigned > total_pending`, a queue row repeats in one
drain, owner or capacity diverges, durable repairs increase unexpectedly, or
API/worker/beat do not run the same commit. Queue cleanup must preserve attempts,
cycles, assignment logs and owner history. Production dry-run, repair, drain,
flags and deploy each require their own explicit authorization.
