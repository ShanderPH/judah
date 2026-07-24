# Master plan: absence-safe automatic assignment

Date: 2026-07-17
Request: `hotfix/agent-absence-eligibility`
Planning phase: `PLAN`
Cycle: `F` (promoted from maintenance because the safe correction is
cross-cutting and changes the assignment protocol)
Implementation status: not started
Production mutations authorized: none

## 1. Outcome

Prevent automatic assignment whenever an agent is absent, away, outside their
individual working hours, out of office, stale, ambiguous, or changing status
too rapidly to be trusted.

The final design must make the following invariant true:

> An assignment can only be committed when a fresh, stable, fail-closed
> eligibility decision for that exact agent has been validated and reserved
> atomically.

This plan addresses both the confirmed incident and the design weaknesses that
allowed it:

- a second writer repeatedly restored Nathan to `online`;
- the Matchmaker trusted that transient local value;
- scheduled absence and individual working hours were not evaluated;
- missing HubSpot availability became `available`;
- the assignment API call happened without an atomic agent reservation;
- audit data could not identify the writer or reconstruct the decision.

## 2. Success criteria

The work is complete only when all criteria below are demonstrably true:

1. An agent with an active HubSpot out-of-office interval is never returned by
   the eligibility query.
2. An agent outside their HubSpot individual working hours is never eligible.
3. `away`, malformed, missing, stale, conflicting, or unmapped HubSpot data is
   ineligible.
4. A transition to ineligible takes effect on the first valid observation.
5. A transition to eligible requires two consecutive consistent samples and
   at least 30 seconds of stable availability.
6. A SAT heartbeat older than 60 seconds makes the agent ineligible.
7. Only one SAT writer can mutate availability at a time; a non-owner cannot
   release another writer's lock.
8. Every status mutation records task ID, runtime identity, source, raw remote
   state hash, and eligibility reason.
9. Immediately before reservation, the Matchmaker locks the agent row and
   re-evaluates eligibility using the database clock.
10. Capacity is reserved before the external HubSpot mutation and compensated
    if that mutation fails.
11. Duplicate tasks and retries cannot create duplicate assignments or inflate
    capacity counters.
12. Operators can globally disable auto-assignment without redeploying.
13. Alerts detect status flapping, multiple writers, stale heartbeats, and
    assignments rejected by the final eligibility guard.
14. The two reported incident timelines are represented as regression tests.

## 3. Non-goals

- Rewriting the ticket-routing priority or fairness algorithm.
- Automatically reassigning historical tickets.
- Modifying HubSpot user schedules or out-of-office periods.
- Solving the unrelated Supabase RLS findings in this request.
- Enabling the dormant AI routing pipeline.
- Treating a manual status override as authority to bypass an active absence.

## 4. Current production flow

```text
HubSpot webhook
    -> task_matchmaker_assign_single
    -> matchmaker_assign_next
    -> select_next_agent
    -> local Agent.status_enum == online
    -> HubSpot owner update
    -> local assignment persistence

Celery Beat every 20s
    -> task_sat_heartbeat
    -> HubSpot Users API
    -> email-keyed status mapping
    -> Agent.status_enum mutation
```

The queue row is protected, but agent eligibility is not reserved atomically.
The external HubSpot update happens before local assignment persistence.

## 5. Target architecture

```text
HubSpot Users API 2026-03
    -> normalized AvailabilityObservation
    -> singleton SAT lease
    -> fail-closed eligibility engine
    -> Agent availability snapshot + audit event

Matchmaker
    -> lock oldest queue row
    -> select candidate from the fresh SAT snapshot
    -> read the selected user directly from HubSpot Users API
    -> reject away, absence, invalid, or failed responses
    -> lock candidate Agent row
    -> recompute persisted eligibility with DB time
    -> create idempotent assignment reservation
    -> reserve capacity
    -> commit transaction
    -> update HubSpot owner
       -> success: finalize assignment
       -> failure: compensate reservation and capacity
```

### 5.0 Webhook limitation and authoritative refresh

HubSpot does not expose webhook subscriptions for the CRM user object or for
`hs_availability_status`. Contact property webhooks are a different object
domain and must not be used to infer agent availability.

A real ticket webhook that enters the NOVO stage therefore performs:

```text
ticket webhook
    -> enqueue ticket idempotently
    -> force an uncached Users API reconciliation
    -> fail closed if the read or reconciliation cannot complete
    -> invoke Matchmaker
    -> re-read the selected HubSpot user immediately before reservation
```

The 20-second Celery Beat remains the background reconciliation and recovery
path. The candidate check is a read-only, idempotent final veto and does not
replace or mutate the continuous SAT snapshot. Neither path consumes
availability from a webhook payload.

### 5.1 Authority order

Signals are evaluated in the following order; the first failing rule wins:

1. Global auto-assignment kill switch.
2. Agent active and `auto_assign_enabled`.
3. Valid HubSpot user identity.
4. Fresh observation, no older than 60 seconds.
5. Active out-of-office interval: ineligible.
6. Remote availability other than `available`: ineligible.
7. Outside individual working hours in the user's IANA timezone: ineligible.
8. Availability not yet stable: ineligible.
9. At or above capacity: ineligible.
10. Otherwise: eligible.

An unavailable signal always takes effect immediately. Available signals are
debounced because false-positive availability creates customer impact, while a
short false-negative only keeps a conversation queued.

### 5.2 Identity

Use immutable IDs, not normalized email, as the primary join:

- `hubspot_owner_id` remains the ticket owner identifier.
- Resolve and persist the account-scoped HubSpot User `hs_object_id`.
- Use email only as a migration/fallback diagnostic.
- Reject duplicate email mappings and emit an alert; never let response order
  choose which status wins.

### 5.3 HubSpot contract

Move the read path behind an adapter for the current versioned Users API:

`GET /crm/objects/2026-03/users`

Request and validate:

- `hs_email`
- `hs_availability_status`
- `hs_out_of_office_hours`
- `hs_working_hours`
- `hs_standard_time_zone`

Parse stringified JSON with explicit schemas. Invalid JSON, an unknown status,
an invalid timezone, or a missing required field must produce an ineligible
decision with a machine-readable reason.

Keep the existing endpoint behind a temporary compatibility flag only during
shadow validation. Do not maintain two long-lived sources of truth.

## 6. Data model

### Agent additions

Recommended fields:

- `hubspot_user_id`: account-scoped user identity; nullable only during
  migration.
- `remote_availability_status`: last raw normalized status.
- `remote_out_of_office_hours`: validated JSON snapshot.
- `remote_working_hours`: validated JSON snapshot.
- `remote_timezone`: validated IANA timezone.
- `availability_observed_at`: timestamp of the remote observation.
- `availability_online_since`: start of the current stable-online candidate.
- `availability_sample_count`: consecutive consistent available samples.
- `eligibility_state`: `eligible`, `ineligible`, or `unknown`.
- `eligibility_reason`: stable reason code.
- `eligibility_evaluated_at`: timestamp of the last decision.
- `availability_writer_id`: runtime/task identity of the last writer.
- `availability_revision`: monotonically increasing revision for optimistic
  checks and audit correlation.

Add database constraints for:

- non-negative sample and capacity counters;
- `current_simultaneous_chats <= max_simultaneous_chats`;
- allowed eligibility states and reason-code compatibility;
- unique non-null `hubspot_user_id`;
- unique `hubspot_owner_id` if production data confirms no duplicates.

Before adding uniqueness, run proof queries and quarantine duplicate identities.

### Availability audit

Extend `AgentStatusHistory` or create a dedicated
`AgentAvailabilityDecision` model containing:

- agent and revision;
- old/new operational status;
- raw remote values or a redacted deterministic hash;
- availability observation timestamp;
- eligibility state and reason;
- task ID, writer ID, deployment ID when available;
- lock token/fencing generation;
- decision timestamp;
- metadata schema version.

Prefer a dedicated append-only decision model if extending the existing table
would mix productivity history with routing evidence.

### Assignment reservation

Create an `AssignmentAttempt` state machine:

- unique idempotency key based on queue/ticket attempt;
- ticket, agent, eligibility revision, and decision snapshot;
- states `reserved`, `external_applied`, `completed`, `compensated`, `failed`;
- reservation/finalization timestamps;
- external error classification;
- retry count.

This becomes the audit boundary between the database transaction and HubSpot.

## 7. Work breakdown

### Phase 0 — Containment and writer attribution

#### OPS-01: Contain known absences

- Disable `auto_assign_enabled` for currently absent agents using an approved
  production change.
- Record who approved, changed, and later restored each agent.
- Do not depend on manually setting `status_enum=away`; the unidentified writer
  can overwrite it.

Acceptance:

- absent agents are excluded by a durable control that SAT does not mutate;
- proof query shows no automatic assignment after containment.

#### OPS-02: Identify and revoke the second writer

- Inventory every Railway project/environment, CI job, developer runtime, and
  external service with production `DATABASE_URL`, Redis, or HubSpot secrets.
- Assign unique `application_name` and `AVAILABILITY_WRITER_ID` values to each
  legitimate runtime.
- Audit Supabase connection logs and Railway task logs.
- Stop the unauthorized/orphaned runtime.
- Rotate production DB/Redis credentials if writer identity cannot be proven.
- Rotation, service restart, or secret revocation requires explicit approval
  and a rollback window.

Acceptance:

- only the intended production Worker can produce SAT audit events;
- no unexplained `away -> online` events occur for at least two heartbeat
  windows before implementation proceeds.

#### OPS-03: Add emergency kill switch

- Add `AUTO_ASSIGNMENT_ENABLED`, defaulting to false when missing in production.
- Gate webhook-triggered, drain-triggered, and backfill-triggered assignment.
- Queue tickets safely while disabled.
- Expose state through the health/diagnostic endpoint without exposing secrets.

### Phase 1 — HubSpot contract and normalized observations

#### BE-01: Introduce typed HubSpot availability schemas

- Add explicit Pydantic v2/domain schemas for working hours, out-of-office
  intervals, timezone, and availability.
- Validate timestamp units and interval ordering.
- Use timezone-aware UTC internally.
- Add reason codes for every malformed or missing condition.

Target files:

- `apps/integrations/hubspot/client.py`
- new `apps/integrations/hubspot/user_availability.py`
- integration tests under `apps/integrations/hubspot/tests/`

#### BE-02: Adopt the versioned Users API

- Implement pagination for `/crm/objects/2026-03/users`.
- Request all five required properties.
- Resolve owner ID to user ID explicitly.
- Add request timeouts, bounded retry with exponential backoff and jitter for
  retryable responses, and rate-limit telemetry.
- Never reuse stale cached `available` data after fetch failure.
- A cached ineligible state may be retained until its explicit expiry.

#### DB-01: Persist HubSpot user identity and availability snapshots

- Add nullable fields first.
- Backfill `hubspot_user_id` with a read-only discovery pass and an auditable
  management command.
- Validate duplicates before adding uniqueness.
- Add indexes that match the final eligibility predicate.
- Supply reversible forward and backward migrations.

### Phase 2 — Singleton SAT and fail-closed state

#### BE-03: Add owner-safe distributed SAT lease

- Acquire a Redis lease using `SET NX` semantics, a unique random token, and a
  bounded TTL.
- Release only if the stored token still matches.
- Record lock acquisition, contention, expiration, and owner identity.
- Add a database revision/fencing check so a delayed task cannot overwrite a
  newer observation after its lease expires.
- Set Celery task expiry below the schedule interval so stale queued heartbeats
  are discarded.
- Configure soft/hard time limits below the lease TTL.
- Make the task idempotent before considering late acknowledgements.
- Keep worker prefetch conservative for the SAT queue.

Recommended initial values, configurable:

- schedule: 20 seconds;
- task expiry: 20 seconds;
- soft time limit: 12 seconds;
- hard time limit: 17 seconds;
- lease TTL: 25 seconds;
- freshness threshold: 60 seconds.

Tune these values from observed production latency before enforcement.

#### BE-04: Centralize eligibility in one pure domain service

Create `apps/support/eligibility_service.py` with:

- typed `EligibilityDecision`;
- stable reason-code enum;
- pure evaluation of active/enabled, freshness, OOO, availability, working
  hours, timezone, stabilization, and capacity;
- no hidden network calls;
- one canonical function used by SAT, queue diagnostics, and Matchmaker.

Recommended initial stabilization:

- two consecutive `available` samples;
- at least 30 seconds since the first consistent available observation;
- immediate demotion on any ineligible sample.

#### BE-05: Replace direct status mutation

- SAT persists the complete observation and decision in one transaction.
- Lock each agent row before applying a revision.
- Ignore older observations and invalid fencing generations.
- Dispatch queue drain only after transaction commit and only when eligibility
  changes to `eligible`.
- Do not let the contact-property webhook mutate authoritative user
  availability. Either remove that fast path or convert it to a hint that
  schedules a fresh Users API read.

### Phase 3 — Race-safe Matchmaker

#### BE-06: Query only decision-ready agents

- Replace `status_enum == online` with the canonical eligibility predicate.
- Include freshness and stable eligibility in the database query.
- Preserve existing fairness rules only after safety filtering.
- Return decision reasons in diagnostics, but redact personal schedule details.

#### BE-07: Reserve agent and capacity atomically

Inside one short `transaction.atomic()`:

1. lock the queue row with `select_for_update(skip_locked=True)`;
2. lock candidate agent rows using deterministic ordering;
3. recompute the canonical eligibility decision using database time;
4. ensure the observed revision still matches;
5. reserve one capacity slot;
6. create an idempotent `AssignmentAttempt`;
7. commit.

Do not keep the transaction open during the HubSpot HTTP call.

After commit:

- apply the HubSpot owner update;
- finalize assignment and audit records on success;
- compensate the reserved capacity and schedule bounded retry on failure;
- make finalize/compensate idempotent;
- alert on an attempt stuck in `reserved`.

#### BE-08: Remove or redirect duplicate assignment paths

The repository currently contains both Matchmaker and legacy
`auto_assign_service` selection paths. Establish Matchmaker as the sole
automatic assignment implementation:

- route all automatic entrypoints through it;
- remove duplicated eligibility/assignment logic after compatibility tests;
- retain explicit manual/admin operations separately.

If removing the legacy path is too risky for the first release, make it call
the canonical reservation service and mark direct execution deprecated.

### Phase 4 — Observability and operational safety

#### OPS-04: Structured decision telemetry

Emit structured events:

- `availability_observed`
- `availability_rejected`
- `availability_writer_conflict`
- `availability_flapping_detected`
- `sat_lease_contended`
- `assignment_reservation_created`
- `assignment_final_guard_rejected`
- `assignment_compensated`

Required dimensions:

- agent ID/owner ID;
- eligibility revision and reason;
- observation age;
- writer/task/deployment identity;
- ticket ID for assignment decisions;
- no email, schedule body, token, or secret.

#### OPS-05: Metrics, SLOs, and alerts

Minimum metrics:

- eligible/ineligible/unknown agents by reason;
- heartbeat duration, age, failures, and lease contention;
- status transitions and flapping per agent;
- assignment reservations by outcome;
- compensation and stuck-reservation counts;
- queue age and depth while no agent is eligible;
- final-guard rejection count.

Initial alerts:

- any agent with more than 6 status transitions in 10 minutes;
- any writer conflict;
- heartbeat age over 60 seconds during business hours;
- any assignment to a revision later proven ineligible;
- reservation stuck longer than 2 minutes;
- compensation failure.

#### DOC-01: Runbooks and architecture documentation

Document:

- authoritative status and identity mapping;
- kill-switch operation;
- absent-agent containment;
- second-writer investigation;
- credential rotation;
- reservation repair;
- rollback steps;
- HubSpot/API degradation behavior.

### Phase 5 — Verification

#### V-01: Unit and contract tests

Cover:

- available, away, missing, empty, and unknown status;
- active/boundary/expired OOO intervals;
- working-hours day groups and boundary minutes;
- IANA timezones and daylight-saving transitions;
- malformed JSON and timestamp units;
- duplicate emails and mismatched IDs;
- stale observations;
- stabilization and immediate demotion;
- precedence of every eligibility reason.

#### V-02: Concurrency tests

Use `TransactionTestCase`/pytest transaction tests with real PostgreSQL
semantics for:

- two workers selecting the same ticket;
- two workers selecting the last capacity slot;
- status revision changing during reservation;
- expired lease followed by a delayed writer;
- duplicate task delivery;
- retry after external success but before local finalization;
- compensation idempotency.

Do not use mocks as the only proof for locking behavior.

#### V-03: Incident regression tests

Encode the two reported timelines:

- an agent becomes `online`, is selected, and changes to `away` seconds later;
- a competing writer tries to restore an older `online` revision;
- the final guard rejects the agent or the stale writer is fenced;
- the ticket stays queued and is later assigned to a truly eligible agent.

#### V-04: Repository quality gates

Run locally:

```powershell
uv run ruff check .
uv run mypy .
uv run pytest apps/support/tests apps/integrations/hubspot/tests
```

Tests that connect to a non-local database require Felipe's explicit approval
because the repository's test isolation can delete data.

#### V-05: Shadow-mode production validation

- Compute and log the new decision without changing routing.
- Compare legacy and new decisions for one complete business day.
- Investigate every case where legacy says eligible and new says ineligible.
- Ensure no PII is emitted.
- Do not enable enforcement until unknown/parse-error rates are understood.

### Phase 6 — Deployment and rollout

#### OPS-06: Feature flags

Recommended flags:

- `AUTO_ASSIGNMENT_ENABLED`
- `ABSENCE_SAFE_ELIGIBILITY_SHADOW`
- `ABSENCE_SAFE_ELIGIBILITY_ENFORCED`
- `ASSIGNMENT_RESERVATION_ENABLED`
- temporary `HUBSPOT_USERS_API_2026_03_ENABLED`

Flags must have safe production defaults and be documented. Avoid permanent
branching; define removal criteria and dates.

#### OPS-07: Migration sequence

1. Deploy additive nullable schema and indexes.
2. Deploy observation parsing and shadow eligibility.
3. Backfill user IDs and validate duplicates.
4. Enable singleton lease and writer telemetry.
5. Enforce absence-safe eligibility.
6. Enable transactional reservation.
7. Remove legacy writer and compatibility endpoint.
8. Apply non-null/unique constraints only after proof queries pass.

#### OPS-08: Canary and enforcement

- Begin with internal/test agents in production.
- Expand to one support subgroup.
- Enable all N1 agents after a monitored business-hour window.
- Keep kill switch immediately available.
- Observe at least 30 minutes after each enforcement step and one complete
  business day before removing compatibility logic.

#### OPS-09: Rollback

Rollback must never restore fail-open behavior.

- Disable new assignment reservations with the kill switch.
- Keep conversations queued.
- Compensate incomplete reservations using the repair command.
- Keep additive schema during rollback.
- Revert to manual assignment if the new eligibility engine is unhealthy.
- Never fall back to treating missing or stale data as `online`.

## 8. Recommended implementation order

1. `OPS-01` contain absent agents.
2. `OPS-02` locate and stop the second writer.
3. `OPS-03` add the global kill switch.
4. `BE-01` through `DB-01` establish the typed HubSpot contract and schema.
5. `BE-03` through `BE-05` make SAT singleton and fail-closed.
6. `BE-06` through `BE-08` make assignment transactional and canonical.
7. `OPS-04`, `OPS-05`, and `DOC-01` complete observability/runbooks.
8. `V-01` through `V-05` complete verification.
9. `OPS-06` through `OPS-09` perform controlled rollout.

Containment and writer attribution are prerequisites. Do not hide an
unidentified production writer behind debounce logic.

## 9. Expected files

Likely modified or added:

- `apps/integrations/hubspot/client.py`
- `apps/integrations/hubspot/user_availability.py`
- `apps/support/eligibility_service.py`
- `apps/support/sat_service.py`
- `apps/support/queue_service.py`
- `apps/support/matchmaker_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/tasks.py`
- `apps/support/models.py`
- `apps/support/migrations/<new_migration>.py`
- `core/settings/base.py`
- `railway.toml` and/or Worker/Beat deployment configuration if required
- support and HubSpot integration test modules
- architecture and operations documentation

Because this exceeds five files and introduces an assignment reservation state
machine, implementation requires explicit approval of the Cycle F promotion.

## 10. Key engineering decisions

| Decision | Recommendation | Reason |
|---|---|---|
| Unknown availability | Ineligible | Routing safety must fail closed |
| OOO precedence | Always ineligible | Explicit scheduled absence is authoritative |
| Working hours | Evaluate in user timezone | Avoid global-schedule mismatch |
| Promotion to eligible | 2 samples and 30s stable | Suppress transient false positives |
| Demotion | Immediate | Prevent assignments during absence |
| Freshness | Maximum 60s | Three heartbeat intervals |
| Identity | HubSpot user ID + owner ID | Email is mutable and collision-prone |
| SAT concurrency | Token-owned lease + fencing | Prevent stale/foreign writers |
| Assignment consistency | Reservation/compensation state machine | Avoid holding DB locks across HTTP |
| Failure behavior | Keep ticket queued | Prefer delay over wrong assignment |
| Legacy path | Remove or delegate | One authoritative assignment implementation |
| Rollout | Shadow, canary, enforce | Measure contract mismatches safely |

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Too many false negatives | Shadow metrics and reason breakdown before enforcement |
| HubSpot API degradation | Fail closed, retain queue, alert, bounded retry |
| Clock/timezone parsing errors | UTC normalization, IANA timezone tests, DB clock |
| Lock expiry during slow call | Short heartbeat work, time limits, fencing revision |
| Capacity leakage | Idempotent reservation compensation and repair command |
| Duplicate identities | Discovery query and quarantine before uniqueness |
| Queue growth during absence | Queue-age SLO and operator visibility |
| Rollback reintroduces incident | Kill switch/manual routing, never fail open |
| Writer remains unidentified | Credential audit/rotation before enforcement |

## 12. Approval gates

Felipe must explicitly approve:

1. Promotion from Cycle M to Cycle F and this master plan.
2. Any production containment mutation.
3. Credential rotation, runtime stop, or service restart.
4. Production migration/deployment.
5. Any test connected to a non-local database.
6. Final enforcement of absence-safe routing.

## 13. Documentation basis

The plan was checked against current primary documentation:

- HubSpot's current Users API exposes separate
  `hs_availability_status`, `hs_out_of_office_hours`,
  `hs_working_hours`, and `hs_standard_time_zone` properties and uses the
  versioned `2026-03` user endpoints.
- Celery recommends atomic task locking with expiring locks for singleton work,
  idempotent task design, bounded time limits, and conservative prefetch/late
  acknowledgement only when retry safety is established.
- Django 5.2 supports short `transaction.atomic()` boundaries and
  `select_for_update()` row locking; concurrency behavior must be tested with
  transaction-aware tests and a database that implements the locks.

## 14. Next action

Felipe reviews and approves or requests changes to this plan. After approval,
start with `OPS-01` and `OPS-02`; do not begin implementation from the
Matchmaker layer while the second production writer is still unexplained.
