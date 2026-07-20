# Research — PR 75: absence-safe agent eligibility

Date: 2026-07-20
Repository: `ShanderPH/judah`
Pull request: `#75` — `hotfix/agent-absence-eligibility` -> `main`
Base SHA: `ff9b3ba353d889ccfa3dce4533403f490958b2be`
Head SHA: `1357d1cc8b0ebe16394d887ed0a9a3ea65713d8a`
Phase: research only; no implementation fix was applied

## 1. Executive verdict

**PR 75 is not mergeable from a correctness or operational-safety
perspective, even though GitHub currently reports the branch as mechanically
mergeable.**

The two failing CI jobs share one immediate blocker: PostgreSQL cannot apply
`support.0016_block_non_authoritative_runtime_writes` because a literal `%` in
the trigger function is passed through Django's schema editor to psycopg as an
invalid placeholder.

Fixing that character alone is insufficient. The review found four broader
release-blocking defects:

1. the kill switch prevents queue ingestion instead of only preventing
   assignment, and defaults to enabled;
2. the documented durable assignment reservation state machine was not
   implemented, leaving an external-success/local-failure split-brain window;
3. the PostgreSQL writer fence fails open for missing or arbitrary
   `application_name` values and does not guard all `agents` routing mutations;
4. a rejected first candidate stops the FIFO drain without trying another
   eligible agent or applying ticket backoff.

The implementation also retains more than 300 lines of unreachable legacy
assignment/SAT code, relies on tokenless Redis locks, leaves at least one
capacity writer without a Python authority guard, and has no production-like
PostgreSQL concurrency tests.

## 2. Scope and evidence reviewed

### GitHub and branch comparison

- PR metadata, commits, files, comments, and checks were inspected with the
  GitHub connector and `gh`.
- The local head exactly matches the PR head.
- `origin/main`, the merge base, and the PR base all resolve to
  `ff9b3ba353d889ccfa3dce4533403f490958b2be`.
- Diff size: 36 files, 3,325 additions, 285 deletions.
- The PR description is still the unfilled repository template.
- There are no human review comments; the only PR comment is the Vercel bot
  preview notification.

### Code chain reviewed

- HubSpot Users API client and availability normalization;
- SAT lease, reconciliation, audit, stabilization, and final remote guard;
- persisted eligibility evaluation and queue filtering;
- Matchmaker selection, capacity reservation, HubSpot mutation,
  compensation, final persistence, and queue drain;
- webhook and Celery entrypoints;
- legacy automatic assignment compatibility paths;
- admin/manual assignment paths;
- models, migrations, settings, readiness diagnostics, tests, and CI;
- existing diagnosis, master plan, handoff, rollout, and verification
  artifacts for this request.

### Current primary documentation consulted

- HubSpot Users API current `2026-03` guide;
- Django 5.2 migration/`RunSQL` behavior;
- psycopg 3 parameter and literal-percent behavior;
- Celery stable guidance for idempotency and `acks_late`.

The current HubSpot contract confirms that the selected endpoint and
properties are valid:

- `/crm/objects/2026-03/users`;
- `hs_availability_status`;
- `hs_out_of_office_hours`;
- `hs_working_hours`;
- `hs_standard_time_zone`;
- account-scoped user `id`/`hs_object_id`, distinct from
  `hubspot_owner_id`.

## 3. CI failure analysis

### B-01 — Blocker: PostgreSQL migration `0016` cannot be applied

Evidence:

- Both failed jobs use the same Actions run:
  `https://github.com/ShanderPH/judah/actions/runs/29617073600`.
- `Tests (Python 3.14)` fails in job `88004556621`.
- `Django System Checks` fails in job `88004556642`.
- The Django system-check command itself is not the failing operation; the
  job later fails at `Apply migrations`.
- Both logs end while applying `support.0016` with:

```text
psycopg.ProgrammingError: only '%s', '%b', '%t' are allowed as
placeholders, got '%''
```

Source:

- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py:21`
  contains the PL/pgSQL `RAISE EXCEPTION` format marker `%`.
- `schema_editor.execute()` supplies a params argument to psycopg, so a
  literal percent must be represented safely for that execution path.

Impact:

- a clean PostgreSQL database cannot reach the PR schema;
- neither CI test execution nor the final migration checks run;
- Railway pre-deploy migration would fail before the new code starts;
- the prior SQLite-only verification could not detect this defect because
  the migration exits early for non-PostgreSQL vendors.

Required planning outcome:

- correct the SQL execution safely;
- add a PostgreSQL migration apply-and-reverse test;
- validate trigger behavior, not only migration graph consistency.

## 4. Release-blocking implementation findings

### C-01 — Critical: the kill switch drops queue ingestion and defaults open

The approved master plan requires `AUTO_ASSIGNMENT_ENABLED` to:

- default to false when missing in production;
- stop assignment;
- keep incoming tickets safely queued.

The implementation does the opposite in two important ways:

1. `core/settings/base.py:188` defaults
   `AUTO_ASSIGNMENT_ENABLED=True` in every environment.
2. `task_matchmaker_assign_single()` checks
   `is_auto_assignment_runtime_allowed()` before `enqueue_new_ticket()`.
   `enqueue_new_ticket()`, `process_new_ticket_event()`, and
   `sync_novo_stage_tickets()` repeat the same combined authority/assignment
   gate before queue creation.

Impact:

- disabling automatic assignment causes new webhook tickets not to enter
  `new_conversations`;
- the daily NOVO-stage reconciliation also declines to rebuild the queue;
- operators lose the safe backlog the kill switch is meant to preserve;
- a missing production variable enables assignment instead of failing safe.

Required planning outcome:

- split `may_ingest_queue` from `may_assign`;
- keep authoritative production ingestion active while assignment is off;
- make the production default fail closed and prove it with configuration
  tests.

### C-02 — Critical: no durable reservation/finalization state machine exists

The master plan specifies an idempotent assignment-attempt record with
`reserved`, `finalized`, `compensated`, and repairable/stuck states. No such
model, migration, or workflow exists in the PR.

The implemented order in `apps/support/matchmaker_service.py` is:

1. increment local capacity under an agent row lock;
2. release the transaction;
3. call HubSpot to change the ticket owner;
4. in a later transaction, delete the queue row and create assignment records.

Compensation runs only for handled exceptions raised by the HubSpot call.
There is no recovery if:

- HubSpot succeeds and the worker crashes before local persistence;
- HubSpot succeeds and the final database transaction fails;
- the hard Celery time limit kills the process in the gap;
- the broker redelivers after an ambiguous outcome.

Impact:

- HubSpot can show an assigned ticket while JUDAH still queues it;
- a retry can assign the same ticket again;
- local capacity can leak;
- audit and fairness counters can diverge;
- there is no authoritative repair command or stuck-attempt metric.

Celery's current guidance permits `acks_late` only for idempotent work. The
SAT task uses `acks_late`, while the assignment pipeline with external side
effects still lacks a durable idempotency protocol.

Required planning outcome:

- implement the state machine promised by the approved plan, or explicitly
  reduce and reapprove the architecture;
- persist an attempt/idempotency key before the external mutation;
- make finalize and compensate independently idempotent;
- reconcile ambiguous provider outcomes before retrying.

### C-03 — Critical: the database writer fence is fail-open and incomplete

`judah_reject_non_authoritative_runtime()` rejects only an
`application_name` matching:

```text
judah:(staging|development|test|preview)
```

It permits:

- an empty `application_name`;
- arbitrary names such as a local SQL client, orphaned worker, or another
  application;
- any name not matching that finite denylist.

This is material because `application_name` is configured only in
`core/settings/production.py`. `DJANGO_ENV=test`, `development`, an unknown
environment name, or a non-Django writer does not necessarily set it.

The `agents` trigger is also only `BEFORE UPDATE OF` a subset of fields. It
does not block non-authoritative:

- `INSERT` or `DELETE` of agents;
- updates to `auto_assign_enabled`, `is_active`,
  `max_simultaneous_chats`, `last_assignment_at`, or other routing inputs.

The Python layer is incomplete as defense in depth:

- `task_reconcile_agent_counts()` updates
  `current_simultaneous_chats` without an authority guard;
- admin/manual assignment entrypoints do not apply the runtime authority
  guard and rely on the database fence.

Impact:

- the defense does not reliably prevent the class of second-writer incident
  this PR is intended to close;
- test mode is always treated as authoritative in Python, even if its database
  configuration is accidentally remote;
- a caller can bypass the denylist by omitting or changing
  `application_name`.

Required planning outcome:

- use an allowlist/fail-closed authority identity, not a non-production
  denylist;
- define trusted migration/operator identities separately;
- set connection identity in every settings mode that can use PostgreSQL;
- cover all routing-state writes and all automatic/manual writer entrypoints;
- add PostgreSQL integration tests for allowed and rejected operations.

### C-04 — Critical: shadow rollout does not itself contain the original risk

Production defaults to shadow enabled and enforcement disabled. In that
state, SAT records the new absence-safe decision but continues projecting
`status_enum=online` solely from remote `available`. Queue selection still
uses the legacy status.

This is intentional shadow behavior, but it means an agent who is
`available` and actively out of office can still receive automatic tickets
during the proposed one-business-day observation window. Stopping the known
staging writer reduces the incident but does not make shadow routing
absence-safe.

Required planning outcome:

- define an explicit containment posture for the shadow window;
- prove absent agents cannot receive work during observation, without relying
  on a manual status value that reconciliation can overwrite.

## 5. High-severity correctness and concurrency findings

### H-01 — Final-guard rejection creates avoidable head-of-line blocking

When the selected agent fails the persisted or remote final guard,
`_reserve_agent_capacity_if_eligible()` returns `None`. `_do_assign()` marks
the ticket queued and returns `NO_AGENT`. `matchmaker_drain_queue()` stops on
that outcome.

The code does not:

- exclude the rejected agent and try the next eligible candidate;
- distinguish provider failure, remote-away, stale snapshot, and real
  no-capacity outcomes at the queue level;
- set `next_assignment_attempt_at` for a final-guard/provider-read failure.

The same oldest ticket and candidate can therefore be retried every drain,
while other valid agents and later tickets wait.

This is separate from the already-known matchmaker head-of-line hotfix:
`_ready_queue()` fixes ticket retry ordering, but candidate rejection still
terminates the drain.

### H-02 — Redis claims are not owner-safe

The per-ticket claim uses:

```python
cache.add(claim_key, "1", timeout=60)
...
cache.delete(claim_key)
```

There is no random owner token and no compare-and-delete release. If work
exceeds the TTL:

1. worker A's lock expires;
2. worker B acquires the same key;
3. worker A finishes and deletes worker B's lock.

The task-level dedup and drain locks use the same pattern. The database queue
row is not durably marked as processing after the initial short transaction,
so Redis expiration plus a crash can permit duplicate external assignment.

### H-03 — Legacy compatibility path ignores its argument and reports the
wrong ticket result

`attempt_auto_assign(new_conv, ...)` now immediately calls the global
`matchmaker_assign_next()` and ignores `new_conv`.

Consequences:

- a legacy caller that enqueues ticket B can cause older ticket A to be
  assigned;
- the function can return `True` to B's caller even though A was assigned;
- the docstring's idempotency claim is not true for the requested
  conversation.

The implementation then leaves the entire former body after the unconditional
return, creating a second large unreachable block.

### H-04 — Manual assignment can claim success after HubSpot failure

`apps/support/admin_api.py::_hubspot_assign()` catches every exception, logs a
warning, and returns normally. `manual_assign()` and force-reassignment then
commit local assignment state and return success.

This pre-existing defect is directly in the touched assignment chain and is
more dangerous after the PR advertises absence-safe/manual eligibility.

Impact:

- JUDAH can say a ticket is assigned to agent B while HubSpot still assigns it
  to agent A or nobody;
- capacity counters and reassignment audit become incorrect;
- operators receive a false-positive API response.

### H-05 — Provider-read failures are collapsed into “missing user”

`HubSpotClient.get_user_by_id()` catches all exceptions and returns `{}`.
The final guard converts that to `MISSING_OBSERVATION`.

This safely vetoes assignment, but loses essential control information:

- `404` cannot be distinguished from `401/403`, `429`, timeout, or `5xx`;
- the queue cannot apply status-aware bounded backoff;
- alerts cannot distinguish identity corruption from provider outage;
- the drain repeatedly revisits the same ready ticket.

The Users API GET paths also do not implement the bounded retry, jitter, or
`Retry-After` handling required by the master plan.

## 6. Maintainability, performance, and contract findings

### M-01 — More than 300 lines of dead legacy implementation remain

- `apps/support/sat_service.py:106-307` is unreachable after
  `_legacy_sat_heartbeat()` immediately returns the new `sat_heartbeat()`.
- `apps/support/auto_assign_service.py` retains the previous assignment body
  after `attempt_auto_assign()` immediately returns through Matchmaker.

This is not harmless documentation. The dead blocks:

- contain stale endpoint guidance and the obsolete two-state contract;
- retain old logging behavior, including agent emails;
- make coverage and review results misleading;
- increase the chance of future edits to the wrong implementation.

### M-02 — Lease TTL begins before a potentially multi-page network read

The 25-second database lease is acquired before the Users API fetch. Each page
has a 10-second timeout and pagination is unbounded by page count. A slow
three-page request can outlive the lease while the original task is active.

Fencing reduces stale writes, but duplicate reconciliation and avoidable lock
contention remain possible. The lease should either cover only the protected
write phase, be renewed safely, or have a TTL derived from a bounded operation
budget.

### M-03 — Audit growth has no retention or partition strategy

`AgentAvailabilityDecision` writes one row per active agent per heartbeat,
including unchanged observations. At a 20-second schedule this is up to 4,320
rows per agent per day before business-hour reduction.

No retention job, partitioning policy, aggregation, or documented storage
budget exists. This will grow the primary operational database continuously
and increase index/write overhead.

### M-04 — Remote contract validation is fail-closed but incomplete

The typed normalizer correctly rejects missing working hours, invalid
timezones, reversed individual intervals, missing identity, and unknown
availability.

However:

- `WorkingHoursWindow.days` is an unrestricted string; unknown values become
  `outside_working_hours` rather than malformed data;
- overlapping working-hours and out-of-office intervals are not validated,
  despite the HubSpot contract forbidding overlap;
- multiple current-time reads are taken during one final evaluation, allowing
  boundary inconsistency at a minute/interval transition.

These are not merge blockers alone, but should be resolved or explicitly
accepted in planning.

### M-05 — Readiness exposes configuration but does not evaluate assignment
readiness

`/api/v1/health/ready` returns authority and feature-flag values, but
`all_ok` ignores them. A production runtime that is non-authoritative, has
stale SAT data, or is missing the expected assignment posture can still report
overall `healthy`.

The endpoint is useful for diagnostics, but it is not yet a reliable deploy
gate for the rollout instructions that depend on it.

## 7. Tests and verification assessment

### Current results

- `ruff check .`: passed.
- `ruff format --check .`: passed.
- Django `check --fail-level WARNING` with local SQLite: passed.
- `makemigrations --check --dry-run` with local SQLite: passed.
- safe local runner: **393 passed**, coverage **64.03%**.
- local mypy did not produce a type result because mypy 2.1.0 crashed while
  constructing `NewSemanalDjangoPlugin`; the GitHub `Lint & Type Check` job,
  including mypy, passed for the PR SHA.
- `git diff --check`: passed.

### Why local green did not predict CI

`run_tests_local.py` intentionally forces SQLite. Migration `0016` exits when
the vendor is not PostgreSQL, so the trigger DDL is never parsed or exercised.
The verification artifact accurately mentions this limitation, but the PR was
still published with `state: VERIFY` and 31 claimed verification runs before a
clean PostgreSQL migration proof.

### Missing tests required before merge

1. Apply and reverse migrations `0015`/`0016` on local PostgreSQL 16.
2. Assert the database fence rejects:
   - staging, development, test, preview, empty, and unknown writers;
   - agent insert/delete and every routing-field update;
   - queue, assignment, lease, and audit mutations.
3. Assert explicitly trusted production/migration/operator identities work.
4. Use real PostgreSQL transaction tests for:
   - two workers selecting one ticket;
   - two workers reserving the last capacity slot;
   - lock expiry and delayed release;
   - SAT fencing after lease expiry;
   - status revision changes during reservation.
5. Crash/failure tests at every boundary:
   - after durable reservation;
   - after HubSpot success;
   - before local finalize;
   - during compensate;
   - redelivery after ambiguous provider outcome.
6. Candidate fallback tests proving one rejected agent does not block another.
7. Kill-switch tests proving tickets remain queued while no assignment occurs.
8. Manual assignment tests proving provider failure returns failure and does
   not commit contradictory local state.
9. Rate-limit/timeout/permission/not-found tests for individual Users API
   reads with typed outcomes and backoff.
10. Audit retention/cleanup tests if per-heartbeat evidence remains.

No test connecting to a non-local database was run during this research.

## 8. Positive implementation findings to preserve

The next phase should retain these sound parts:

- the selected HubSpot Users API `2026-03` contract and account-scoped user
  identity are current;
- missing/unknown remote availability fails closed;
- out-of-office takes precedence over `available`;
- working hours are evaluated in the user's IANA timezone;
- promotion requires stabilization while demotion is immediate;
- queue filtering includes freshness when enforcement is enabled;
- candidate capacity is re-evaluated under `select_for_update()`;
- the final assignment guard performs an uncached individual Users API read;
- the false contact-property availability webhook writer was removed;
- availability decisions include revision, writer, task, reason, timestamp,
  state hash, and fencing generation;
- the SAT database lease uses an owner token for release;
- the status mutation fields were removed from the support API and made
  read-only in Django Admin.

## 9. Documentation and delivery inconsistencies

- The PR body contains no description, test instructions, migration list, or
  risk statement despite a 36-file, database-changing hotfix.
- `STATUS.md` says `VERIFY`, while two mandatory checks fail.
- The walkthrough claims PostgreSQL triggers reject non-authoritative writes,
  but the only clean PostgreSQL execution currently fails before trigger
  installation.
- The master plan requires a durable assignment reservation state machine,
  repair command, stuck metrics, and concurrency tests; none were delivered.
- The master plan requires a production-safe false default and safe queueing
  under the kill switch; implementation and operations documentation specify
  `AUTO_ASSIGNMENT_ENABLED=true`.
- The rollout calls for a canary subgroup, but enforcement is a single global
  boolean with no canary cohort mechanism.

## 10. Planning inputs and acceptance boundary

Planning should group remediation into these ordered workstreams:

1. **Restore a truthful baseline:** fix/retest PostgreSQL migrations and make
   CI execute the actual suite.
2. **Separate ingestion from assignment:** safe kill switch, safe defaults,
   and backlog preservation.
3. **Close writer isolation:** fail-closed database identity plus complete
   Python entrypoint guards.
4. **Implement durable assignment attempts:** idempotent reserve, provider
   mutation, finalize, compensate, reconcile, and repair.
5. **Remove head-of-line and lock races:** candidate iteration, typed backoff,
   owner-safe locks, and durable claims.
6. **Remove dead paths:** one canonical SAT and one canonical assignment
   implementation.
7. **Harden manual operations and provider failures:** no swallowed assignment
   errors or false success.
8. **Add production-like verification:** PostgreSQL 16, concurrency, crash
   boundaries, and migration reversal.
9. **Align docs and rollout:** accurate PR body, STATUS/HANDOFF, containment,
   canary mechanism, retention, and readiness criteria.

The implementation phase must not be considered complete until:

- every GitHub Actions check for PR 75 is green;
- the full suite runs after migrations on PostgreSQL 16;
- kill-switch queue preservation and writer isolation are proven;
- ambiguous HubSpot success cannot duplicate or lose an assignment;
- concurrent workers cannot exceed capacity or assign one ticket twice;
- no unreachable legacy SAT/assignment implementation remains;
- operational documentation matches the code actually shipped.
