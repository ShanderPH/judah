# Production diagnosis: absent agents remain eligible

Date: 2026-07-17
Scope: read-only investigation
Reported tickets: `46846494979`, `46850988602`
Reported agent: Nathan

## Executive finding

The two reported tickets were assigned because Nathan was stored as `online`
at the exact instant the Matchmaker selected him. This local state was not
stable or trustworthy: production recorded **330 status transitions for
Nathan on 2026-07-17** (165 to `online`, 165 to `away`), while the next-highest
agent had only 3.

The production Railway Worker consistently wrote `online -> away`. A second
writer consistently restored `away -> online` shortly afterwards. Those
reverse transitions exist in `agent_status_history` with
`sync_source=sat_heartbeat`, but there are no corresponding log events in the
active Worker, API, or Beat services. There is only one active Worker replica,
one Beat replica, and one enabled 20-second `sat-heartbeat` periodic task.

Therefore the immediate incident cause is a **dual-writer status race**:
an unobserved process using the same production database is restoring Nathan
to `online`, opening a short eligibility window in every cycle. The Matchmaker
selected Nathan inside that window for both reported tickets.

The code also has two independent safety defects that make this race harmful:

1. eligibility trusts a single mutable `Agent.status_enum == online` value
   without heartbeat freshness, stabilization, or absence checks;
2. scheduled absence/out-of-office is not fetched, and missing
   `hs_availability_status` fails open to `available`.

## Expected flow

1. Celery Beat executes `task_sat_heartbeat` every 20 seconds during global
   business hours.
2. `sat_heartbeat()` calls
   `HubSpotClient.get_all_owners_availability()`.
3. The HubSpot client requests only `hs_email,hs_availability_status`.
4. The heartbeat maps the result by email and writes `Agent.status_enum`.
5. `queue_service.get_eligible_agents()` filters only by local
   `status_enum == online`, feature enablement, active flag, and capacity.
6. `select_next_agent()` can select any row that passed that filter.

## Confirmed code defects

### 1. Out-of-office is never fetched or evaluated

The current HubSpot Users API documents three separate concepts:

- `hs_availability_status`: `available` or `away`;
- `hs_out_of_office_hours`: scheduled absence date ranges;
- `hs_working_hours`: the user's individual work schedule.

JUDAH requests only `hs_email,hs_availability_status` in
`apps/integrations/hubspot/client.py`. Neither
`hs_out_of_office_hours` nor `hs_working_hours` is requested or evaluated.

The local `Agent.working_hours` field also does not participate in
`get_eligible_agents()`. The only schedule gate is the global
`is_business_hours()` check, which cannot represent Nathan's individual
absence.

Consequently, HubSpot can truthfully return `available` while a separate
out-of-office interval says the user must not receive work. JUDAH sees only the
first signal.

### 2. Missing availability fails open

In `get_all_owners_availability()`:

```python
availability = props.get("hs_availability_status") or "available"
```

An omitted, null, or empty property is promoted to `available`, and then to
local `online`. For assignment safety, unknown availability must not create
eligibility.

### 3. Local status fidelity is lower than the model suggests

`Agent.StatusEnum` declares `online`, `away`, `offline`, and `busy`, but the
HubSpot polling path emits only:

- `available` -> `online`;
- every other non-empty value -> `away`.

The webhook task follows the same two-state mapping. The synchronization flow
therefore cannot derive `offline` or `busy`, and the meaning of the stored
status is narrower than the API/admin model communicates.

### 4. Native user availability and the webhook fast path are different domains

The canonical polling source is the HubSpot Users API. The optional fast path
in `hubspot_handler.py`, however, listens for
`contact.propertyChange/hs_availability_status` and resolves a contact email.
The official availability field documented for this use case belongs to the
user object. No evidence was found that this contact webhook can reliably
represent native HubSpot user availability or out-of-office intervals.

### 5. Test coverage encodes the incomplete two-state contract

The existing tests cover `available -> online` and `away -> away`. There is no
coverage for:

- active `hs_out_of_office_hours`;
- individual working hours;
- absent/null `hs_availability_status`;
- unknown status failing closed;
- assignment rejection when the heartbeat is stale.

## Relationship to the reported tickets

### Ticket `46846494979`

- Entered the queue: `2026-07-17 14:43:59.163Z`
  (`11:43:59.163 America/Sao_Paulo`).
- Nathan changed `away -> online`: `14:43:55.811Z`.
- Worker selected Nathan: `14:44:11.898Z`.
- HubSpot owner `88093732` was applied: `14:44:12.286Z`.
- Assignment persisted: `14:44:12.453Z`; queue wait `13.12s`.
- Nathan changed `online -> away`: `14:44:14.912Z`, only `2.459s`
  after assignment.
- Unobserved writer changed him back `away -> online`:
  `14:44:15.826Z`.

### Ticket `46850988602`

- Entered the queue: `2026-07-17 15:04:16.030Z`
  (`12:04:16.030 America/Sao_Paulo`).
- Nathan changed `away -> online`: `15:04:09.716Z`.
- Worker selected Nathan: `15:04:27.363Z`.
- HubSpot owner `88093732` was applied: `15:04:27.892Z`.
- Assignment persisted: `15:04:28.056Z`; queue wait `11.86s`.
- Nathan changed `online -> away`: `15:04:29.261Z`, only `1.205s`
  after assignment.

For both tickets, the last stored state before assignment was `online`, so
`get_eligible_agents()` behaved according to its current contract. The defect
is that the contract treats this rapidly oscillating, single-source flag as
sufficient proof of eligibility.

### Scale and specificity

Production status-transition counts for 2026-07-17:

| Agent | Total | To online | To away |
|---|---:|---:|---:|
| Nathan Rodrigues | 330 | 165 | 165 |
| Esther Finotti | 3 | 1 | 2 |
| Raphael Loera | 2 | 1 | 1 |
| Joao Santos | 1 | 1 | 0 |

This is not normal portal-wide presence churn; it is isolated to Nathan.

### Dual-writer evidence

- Active Railway topology: 1 API, 1 Worker, 1 Beat, 1 Redis.
- Worker concurrency: 2; Beat schedule: one task every 20 seconds.
- Database scheduler contains exactly one enabled `sat-heartbeat` entry.
- No database trigger changes agent status; the only trigger on `agents`
  updates `updated_at`.
- Worker logs contain every observed `online -> away` transition.
- Worker logs contain zero `new_status=online` transitions in the incident
  window.
- API and Beat logs contain no Nathan status writes in the same window.
- Database nevertheless contains the reverse transitions, all labelled
  `sat_heartbeat`.
- No `hs_availability_status` webhook event was stored in the incident window.

The second writer could be another environment, an external worker/local
process, or an orphaned runtime using production credentials. Railway can
prove it is not one of the four active services in this project, but cannot
identify processes outside the project from its own telemetry.

## External access results

### HubSpot

The official current Users API documentation was fetched successfully. The
runtime is authenticated and the Railway logs prove successful owner updates
for both tickets. The operational connector exposed to this session provides
developer/docs operations rather than arbitrary CRM record reads, so Nathan's
current `hs_out_of_office_hours` value was not independently read. No HubSpot
record was changed.

### Railway

Railway MCP confirmed all four production services healthy on the July 15
deployment. Replica counts, service configuration, deployment history, and
incident-window logs were inspected read-only. No deployment, variable,
service, queue, or environment setting was changed.

### Database

Supabase MCP queried the JUDAH production project using `SELECT` only. It
correlated `assignment_logs`, `agent_status_history`, `agents`,
`django_celery_beat_periodictask`, `webhook_events`, database triggers, and
active connections. No row or schema was changed.

## Root-cause classification

- Immediate production cause: a second, unobserved `sat_heartbeat` writer
  repeatedly restores Nathan to `online`.
- Assignment race: both tickets landed inside the short false-online window.
- Primary design weakness: eligibility trusts one mutable status value with no
  freshness or stabilization requirement.
- Absence-model defect: scheduled out-of-office and individual working hours
  are ignored.
- Safety amplifier: missing availability defaults to eligible.
- Observability gap: status history does not store writer/task identity,
  remote raw values, out-of-office decision, or heartbeat age.
- Contract gap: four local status values are exposed, but synchronization
  derives only two.

## Immediate containment options (not executed)

1. Set `auto_assign_enabled=false` for absent agents until absence-aware
   eligibility is deployed.
2. Stop or isolate the unidentified second writer after locating which
   environment/process shares production credentials.
3. Do not rely on manually setting Nathan to `away`: the second writer will
   overwrite it.
4. Do not reassign the reported tickets automatically without explicit
   approval.

## Recommended fix direction (not implemented)

1. Fetch `hs_out_of_office_hours`, `hs_working_hours`, timezone, email, and
   availability from the current Users API.
2. Compute a single fail-closed eligibility decision for the current instant:
   active, enabled, fresh heartbeat, available, within individual working
   hours, not out of office, and below capacity.
3. Add a distributed lock/single-writer lease to `sat_heartbeat`.
4. Require a stable-online interval or multiple consistent samples before an
   agent becomes assignment-eligible; transitions to ineligible remain
   immediate.
5. Treat missing/malformed remote status as ineligible.
6. Persist task ID, runtime identity, remote signals, and decision reason used
   at assignment time.
7. Add regression tests for dual writers, active absence, boundary timestamps,
   timezone, missing status, stale heartbeat, and normal available users.

## Separate database security observation

The Supabase advisor reports Row Level Security disabled on seven public
tables: `token_blacklist_blacklistedtoken`,
`token_blacklist_outstandingtoken`, `conversation_instances`, `agent_runs`,
`conversation_state_transitions`, `tool_call_audit_logs`, and
`conversation_events`. This is not the cause of the assignment incident and
was not modified, but it should be handled as a separate security request.
