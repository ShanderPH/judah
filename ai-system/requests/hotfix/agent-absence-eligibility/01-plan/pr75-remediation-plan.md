# PR 75 remediation plan: absence-safe agent eligibility

Date: 2026-07-20
Request: `hotfix/agent-absence-eligibility`
Pull request: `#75`
Cycle: `F`
Phase: `PLAN`
Implementation status: paused at PR head `1357d1c`
Production mutations authorized: none

## 1. Planning decision

PR 75 must not be merged or deployed in its current state. This plan preserves
the sound availability work already present in the branch, but replaces the
incomplete delivery sequence with a release-gated remediation.

This document supplements the original `01-plan/master-plan.md`. The original
plan remains the architectural record; this document is the executable plan
for correcting the implementation reviewed in
`00-context/research.md`.

No implementation, migration, deployment, feature-flag change, or production
database operation is authorized by this plan.

## 2. Invariants

The remediation is complete only when all of these invariants hold:

1. Turning automatic assignment off never prevents authoritative ticket
   ingestion or queue reconciliation.
2. Missing production configuration fails closed for assignment.
3. A database writer without an explicitly trusted database identity cannot
   mutate any routing state.
4. `application_name` is diagnostic context, not the sole security boundary.
5. Every external owner mutation has a durable idempotency record created
   before the HubSpot request.
6. A worker crash at any boundary can be reconciled without duplicate
   assignment, leaked capacity, or false local success.
7. Rejection of one candidate does not prevent evaluation of another eligible
   candidate.
8. Redis lock expiry cannot let one worker release another worker's lock.
9. There is one canonical SAT implementation and one canonical automatic
   assignment implementation.
10. PostgreSQL 16 migration, trigger, transaction, and concurrency behavior is
    proven before merge.
11. Shadow observation never exposes tickets to the legacy unsafe eligibility
    path.
12. Manual assignment never reports success when HubSpot did not apply the
    owner.

## 3. Scope

### Preserve

- HubSpot Users API `2026-03` and account-scoped user identity.
- Typed, fail-closed availability normalization.
- Out-of-office precedence and IANA-timezone working-hours evaluation.
- Immediate demotion and stabilized promotion.
- Freshness-aware persisted eligibility.
- Uncached individual Users API read as the final remote veto.
- SAT owner token, database lease, fencing generation, and decision audit.
- Read-only status fields in support API and Django Admin.
- Removal of the false contact-property availability webhook path.

### Correct or complete

- PostgreSQL migration execution and reversal.
- Assignment/ingestion feature-gate separation.
- Database and Python writer authority.
- Durable assignment attempts and recovery.
- Candidate fallback, queue backoff, and owner-safe claims.
- Manual assignment consistency.
- Typed HubSpot failures and bounded retry.
- Dead legacy code.
- Audit retention and truthful readiness.
- PostgreSQL CI, crash-boundary tests, and rollout controls.

### Non-goals

- Changing ticket priority or fairness after safety filtering.
- Reassigning historical tickets automatically.
- Modifying HubSpot schedules or absence data.
- Solving unrelated Supabase RLS findings.
- Deploying or mutating production during implementation.

## 4. Execution order and stop gates

Work must proceed in the following order. A failed stop gate blocks every
later workstream.

```text
Gate A: truthful PostgreSQL baseline
  -> Gate B: queue-safe controls and writer isolation
    -> Gate C: durable assignment protocol
      -> Gate D: canonical paths and provider semantics
        -> Gate E: production-like verification
          -> Gate F: controlled rollout approval
```

### Gate A

- Migrations apply and reverse on disposable local PostgreSQL 16.
- CI reaches and executes the real test suite after migrations.
- The corrected trigger behavior is covered by integration tests.

### Gate B

- Assignment can be disabled while ingestion and queue repair remain active.
- Missing production flags fail closed.
- Trusted and untrusted database writer identities are proven.
- Every routing-state writer has a Python authority guard where applicable.

### Gate C

- Assignment attempts survive worker crashes and redelivery.
- Finalize, compensate, and reconcile are independently idempotent.
- Candidate rejection and provider degradation have bounded behavior.

### Gate D

- Dead SAT and assignment implementations are removed.
- Automatic entrypoints use one orchestrator.
- Manual operations cannot create HubSpot/local split brain.
- Readiness and operational telemetry describe the real gate.

### Gate E

- The full quality suite passes on PostgreSQL 16.
- Concurrency and crash-boundary tests pass repeatedly.
- All required GitHub checks for the PR are green.
- Documentation matches the implementation.

### Gate F

- Felipe explicitly approves deployment.
- Shadow observation runs with assignment disabled and ingestion enabled.
- Canary routes only through enforced absence-safe eligibility.
- Full enforcement requires a second explicit approval.

## 5. Work breakdown

### Workstream 0 - Restore a truthful baseline

#### DB-02: Repair migration `support.0016`

Decision:

- Because `0016` has not successfully applied in the PR's PostgreSQL CI, edit
  it in place only after confirming it has not been applied in any shared
  environment.
- If any shared environment already records `0016` as applied, preserve it and
  add a corrective `0017`; do not rewrite applied migration history.
- Execute PL/pgSQL without psycopg interpreting literal `%` markers as client
  placeholders. Prefer Django `RunSQL` or an execution path whose literal
  percent handling is explicit and tested.
- Keep the reverse operation complete and deterministic.

Target files:

- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py`
- new PostgreSQL migration tests under `apps/support/tests/`

Acceptance:

- clean PostgreSQL 16 applies `0015` then `0016`;
- reverse to `0014` removes every trigger and function;
- reapply succeeds;
- tests execute a rejected and an allowed write after installation;
- no SQLite-only pass is accepted as migration proof.

#### OPS-07: Make CI execute the actual suite

- Provision PostgreSQL 16 and Redis services in GitHub Actions.
- Apply migrations before tests and fail immediately on migration errors.
- Run the full pytest suite after migration, not only Django checks.
- Retain SQLite as an optional fast developer lane, never as the release gate.
- Add a test safety assertion that refuses non-local/non-ephemeral database
  targets.

Acceptance:

- test output proves tests ran after successful PostgreSQL migrations;
- the CI database is disposable and uniquely named;
- no test command can resolve to production or staging credentials.

### Workstream 1 - Separate queue ingestion from assignment

#### BE-09: Split runtime capabilities

Replace the combined gate with explicit capabilities:

- `may_ingest_queue`: authoritative runtime may create/update queue rows even
  when assignment is disabled;
- `may_reconcile_queue`: authoritative runtime may rebuild NOVO-stage backlog;
- `may_assign`: authoritative runtime and assignment feature switch are both
  enabled.

Apply them consistently to:

- ticket webhook task;
- `enqueue_new_ticket()`;
- ticket lifecycle ingestion;
- NOVO-stage synchronization;
- single-ticket assignment;
- queue drain and legacy compatibility entrypoints.

Target files:

- `apps/support/availability_runtime.py`
- `apps/support/tasks.py`
- `apps/support/matchmaker_service.py`
- `apps/support/auto_assign_service.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `core/settings/base.py`
- `core/settings/production.py`

Acceptance:

- with assignment disabled, a new ticket is queued exactly once;
- the drain performs no owner mutation;
- backlog reconciliation still restores missing queue rows;
- enabling assignment drains the preserved backlog;
- missing production configuration leaves assignment disabled;
- development/test behavior must be explicit, not inherited from a permissive
  global default.

#### OPS-08: Define safe shadow and canary controls

- Shadow observation runs with `AUTO_ASSIGNMENT_ENABLED=false`.
- Ingestion, reconciliation, and decision telemetry stay active.
- Add an explicit canary allowlist of agent IDs. While the allowlist is set,
  automatic routing considers only allowlisted agents and always enforces the
  new eligibility decision.
- Do not send non-canary tickets through legacy eligibility.
- Removing the canary restriction requires an explicit rollout action.

Acceptance:

- absent agents cannot receive automatic tickets during shadow;
- canary assignments cannot bypass enforced eligibility;
- queue age/depth remain observable while assignment is disabled.

### Workstream 2 - Close writer isolation

#### DB-03: Replace the fail-open writer denylist

Decision:

- Use dedicated PostgreSQL roles/credentials as the authority boundary.
- Production runtime, migration, and break-glass operator identities are
  separate and explicitly allowlisted.
- Staging, preview, development, test, empty, and unknown identities fail
  closed.
- `application_name` is required for attribution and diagnostics, but does not
  grant authority by itself.
- Rotate/isolate production credentials before relying on the fence; a second
  process holding the same trusted credential is indistinguishable at the
  database privilege layer.

The trigger must cover:

- `INSERT`, `UPDATE`, and `DELETE` on `agents`;
- every routing input, including active/enabled/capacity/fairness fields;
- queue rows, assignments, assignment logs, availability decisions, leases,
  and the new assignment-attempt table.

Target files:

- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py`
  or the corrective successor selected by DB-02;
- `core/settings/base.py`;
- `core/settings/production.py`;
- deployment documentation.

Acceptance:

- trusted production runtime writes succeed;
- trusted migration identity can apply/reverse schema changes;
- explicit break-glass access is audited;
- staging, development, test, preview, empty, unknown, and arbitrary client
  identities are rejected;
- changing only `application_name` cannot elevate an untrusted DB role.

#### BE-10: Complete Python defense in depth

- Inventory every write to routing tables and fields.
- Add capability checks to automatic reconciliation, manual/admin entrypoints,
  lifecycle repair, SAT, and count reconciliation.
- `task_reconcile_agent_counts()` must not write from an unauthorized runtime.
- Tests must enumerate entrypoints so new writers cannot silently bypass the
  guard.

Acceptance:

- each writer is mapped to a required capability;
- unauthorized entrypoints fail before network or database mutation;
- tests cover the count reconciler and manual/admin paths.

#### OPS-09: Credential and environment prerequisite

Before any shared-environment migration:

- staging receives isolated database and Redis credentials;
- production credentials are rotated if prior sharing cannot be disproved;
- every service sets a unique diagnostic `application_name`;
- Railway service/environment topology is recorded;
- rollback credentials and break-glass ownership are documented.

This task requires Felipe's explicit approval because it changes external
infrastructure and credentials.

### Workstream 3 - Implement durable assignment attempts

#### DB-04: Add the assignment attempt state machine

Create `AssignmentAttempt` with:

- immutable idempotency key;
- ticket, queue row, selected agent, and eligibility revision;
- desired HubSpot owner and prior observed owner;
- decision snapshot and reason;
- states `reserved`, `external_applied`, `completed`, `compensating`,
  `compensated`, `retryable`, and `repair_required`;
- provider request/result classification;
- reservation, external-apply, finalize, compensate, and update timestamps;
- retry count, next retry time, and last error code;
- unique constraints preventing multiple live attempts for one ticket;
- indexes for stuck/retryable repair scans.

Add durable queue-claim fields:

- owner token;
- claim expiry;
- claim/update timestamp.

Migrations must be reversible and PostgreSQL-tested. Constraints must keep
capacity non-negative and prevent duplicate completed assignment records.

#### BE-11: Reserve atomically

Inside one short transaction:

1. claim and lock the oldest ready queue row;
2. lock candidate agents in deterministic order;
3. evaluate the persisted decision with one database timestamp;
4. verify the exact availability revision;
5. reserve capacity;
6. create or reuse the durable assignment attempt;
7. commit before the network call.

No transaction remains open during HubSpot I/O.

Acceptance:

- two workers cannot reserve the same ticket;
- two workers cannot reserve the last capacity slot;
- redelivery reuses the attempt instead of creating another;
- revision changes invalidate reservation safely.

#### BE-12: Apply, finalize, compensate, and reconcile idempotently

- Apply the HubSpot owner mutation using the durable attempt.
- On clear success, mark `external_applied`, then finalize queue, assignment,
  audit, and capacity state idempotently.
- On clear provider rejection, compensate idempotently and schedule bounded
  retry only when appropriate.
- On timeout, worker loss, or ambiguous response, do not blindly repeat the
  mutation. Read the ticket's current HubSpot owner:
  - target owner present: finalize;
  - prior/no owner present and retry budget remains: retry safely;
  - conflicting owner or unreadable state: mark `repair_required`.
- Add a repair task/management command and stuck-attempt metric.

Acceptance:

- crash after reservation is repairable;
- crash after HubSpot success finalizes without a second assignment;
- final local transaction failure is repairable;
- repeated finalize/compensate calls have one effect;
- capacity is neither leaked nor decremented twice;
- ambiguous outcomes never become false success.

### Workstream 4 - Remove queue and lock races

#### BE-13: Iterate candidates and classify rejection

- Evaluate ordered candidate IDs one at a time.
- A persisted or remote guard rejection excludes that candidate for the
  current attempt and continues to the next candidate.
- Capture typed reasons: remote away/absence, stale revision, capacity,
  malformed identity, provider unavailable, and no eligible agent.
- Stop the drain only for a real queue-wide condition, not one rejected
  candidate.
- Apply ticket backoff after all candidates are exhausted or a provider-wide
  outage is detected.

Acceptance:

- candidate A rejected and candidate B eligible assigns to B;
- repeated provider failure does not hot-loop the oldest ticket;
- later ready tickets are not blocked by a backed-off ticket;
- fairness order is preserved among safe candidates.

#### BE-14: Make claims owner-safe and durable

- Use random owner tokens for Redis dedup/drain locks.
- Release through atomic compare-and-delete.
- Treat Redis only as an optimization; the database queue claim and
  `AssignmentAttempt` are the correctness boundary.
- Bound lock TTLs from measured operation budgets and renew only with
  owner-token verification.

Acceptance:

- an expired owner cannot delete a successor's lock;
- Redis loss or eviction does not permit duplicate external assignment;
- delayed worker tests prove claim fencing.

### Workstream 5 - Canonical paths and provider semantics

#### BE-15: Remove dead SAT and assignment code

- Remove the unreachable legacy SAT body.
- Remove the unreachable legacy `attempt_auto_assign()` body.
- Make Matchmaker plus the durable attempt orchestrator the only automatic
  assignment implementation.
- Make compatibility functions operate on the requested ticket and return
  that ticket's result.
- Remove stale two-state comments, logs, and tests.

Acceptance:

- no unconditional return leaves a second implementation behind;
- code search finds one SAT write path and one automatic assignment protocol;
- compatibility tests prove ticket identity is preserved.

#### BE-16: Introduce typed HubSpot outcomes

- Do not collapse every `get_user_by_id()` failure into `{}`.
- Distinguish not found, unauthorized/forbidden, rate limited, timeout,
  retryable server error, malformed payload, and success.
- Implement bounded retry with jitter for safe GETs and honor `Retry-After`.
- Evaluate a decision with one captured `now`.
- Validate working-hour day values and forbidden interval overlaps.
- Redact tokens, email, and schedule bodies from logs.

Acceptance:

- queue behavior and telemetry differ correctly for `404`, `401/403`, `429`,
  timeout, and `5xx`;
- final eligibility remains fail closed;
- retries are bounded and observable.

#### BE-17: Make manual assignment truthful

- `_hubspot_assign()` must return a typed result or raise a typed error.
- Never persist local assignment success after HubSpot failure.
- Reuse the durable attempt/finalization protocol where practical.
- Define explicit audited behavior for a manual eligibility override; a normal
  manual action must not silently bypass absence safety.
- Force operations require permission, reason, and audit evidence.

Acceptance:

- provider failure returns a failed API response and leaves consistent local
  state;
- retries do not inflate capacity;
- force behavior is explicit and tested.

### Workstream 6 - Operations, retention, and readiness

#### OPS-10: Add decision retention

- Retain detailed availability decisions for a configurable bounded period,
  initially 30 days.
- Delete in bounded batches with metrics and an auditable scheduled task.
- Preserve longer-lived aggregate counters needed for incident analysis.
- Document expected rows/day, storage budget, and index maintenance.

Acceptance:

- unchanged heartbeat evidence does not grow without bound;
- cleanup is idempotent and does not lock the hot assignment path.

#### OPS-11: Make readiness a deployment gate

Readiness must evaluate, not merely display:

- authoritative runtime identity;
- assignment switch posture;
- expected writer identity;
- migration availability;
- SAT heartbeat freshness when assignment is enabled;
- absence-safe enforcement/canary posture;
- stuck assignment attempts.

Return unhealthy/degraded machine-readable reasons suitable for Railway gates.

Acceptance:

- non-authoritative or stale assignment runtimes cannot report fully ready;
- assignment-disabled ingestion-only mode is represented truthfully;
- no secret or schedule body is exposed.

## 6. Verification plan

### V-06: Migration and writer-fence tests

On disposable local PostgreSQL 16:

- apply/reverse/reapply `0015` and `0016` or successor;
- validate every allowed and rejected identity;
- test agent insert/delete and all routing-field updates;
- test queue, assignment, attempt, lease, audit, and capacity writes.

### V-07: Queue control tests

- assignment off plus ingestion on;
- queue reconciliation while assignment is off;
- missing production flag defaults;
- backlog drain after enablement;
- canary allowlist cannot fall back to legacy routing.

### V-08: Transaction and concurrency tests

Use PostgreSQL `TransactionTestCase`/transactional pytest for:

- two workers and one ticket;
- two workers and one capacity slot;
- candidate revision change during reservation;
- Redis expiry and delayed release;
- durable claim expiry;
- SAT lease expiry and stale writer fencing.

### V-09: Crash-boundary and redelivery tests

Inject failure:

- after durable reservation;
- after provider success;
- before local finalize;
- during compensation;
- during ambiguous provider timeout;
- before and after Celery redelivery.

Prove the repair command converges every state.

### V-10: Provider and manual-operation tests

- individual Users API `404`, `401/403`, `429`, timeout, and `5xx`;
- `Retry-After` and bounded retry;
- rejected candidate followed by eligible candidate;
- manual provider failure and explicit force audit;
- no PII in structured logs.

### V-11: Repository gates

Run only against verified local/ephemeral services:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
uv run pytest
git diff --check
```

Before any pytest invocation, prove the database target is local and
disposable. Tests connecting to a non-local database require Felipe's explicit
approval because `conftest.py:isolate_db` can delete data.

Required evidence:

- command, timestamp, database identity, exit code, and result summary;
- migration apply/reverse output;
- repeated concurrency/crash-test results;
- links to green GitHub checks for the final PR SHA.

## 7. Delivery slices

Keep commits reviewable and preserve a green or intentionally gated state:

1. `fix(db): repair routing writer migration`
2. `ci(test): validate routing on postgres`
3. `fix(support): preserve queue with assignment disabled`
4. `fix(db): enforce trusted routing writers`
5. `feat(support): persist assignment attempts`
6. `fix(support): reconcile assignment outcomes`
7. `fix(support): continue after candidate rejection`
8. `fix(support): make routing claims owner safe`
9. `refactor(support): remove legacy assignment paths`
10. `fix(hubspot): classify routing provider failures`
11. `fix(support): keep manual assignment consistent`
12. `test(support): cover routing concurrency and recovery`
13. `docs(support): align absence-safe rollout`

Exact commit boundaries may combine inseparable migration/model changes, but
implementation, tests, and operational documentation must remain easy to
review. Do not include pre-existing `.gitignore`, `docs/evidences/`, or
`uv.lock` drift unless separately authorized and proven necessary.

## 8. Rollout plan

No rollout starts until Gate E is complete.

1. Obtain Felipe's explicit approval.
2. Confirm isolated staging database/Redis and trusted DB roles.
3. Apply and reverse migrations once on disposable staging infrastructure.
4. Deploy with ingestion on, assignment off, shadow on.
5. Observe one complete business day and resolve every malformed/unknown
   decision.
6. Configure an explicit canary agent allowlist.
7. Enable assignment only for enforced canary routing.
8. Observe queue depth/age, provider outcomes, stuck attempts, compensation,
   writer rejection, SAT freshness, and final-guard rejection.
9. Obtain explicit approval for full enforcement.
10. Remove canary restriction while keeping absence-safe enforcement on.
11. Keep the global assignment kill switch immediately available.

Rollback:

- disable assignment while preserving ingestion;
- do not roll back a migration while live attempts exist;
- reconcile or compensate non-terminal attempts first;
- preserve attempt and audit evidence;
- revert application code only after the queue and attempt state is stable.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Migration history differs between environments | Verify `django_migrations` read-only before choosing edit-in-place versus corrective migration. |
| DB identity design blocks legitimate operations | Separate runtime, migration, and break-glass roles; test each on PostgreSQL 16. |
| HubSpot success is ambiguous | Re-read current owner and reconcile durable attempt before retry. |
| Queue grows during safe shadow | Keep ingestion active, alert on queue age/depth, and communicate expected backlog. |
| Canary accidentally uses legacy routing | Restrict candidate query to enforced canary agents; no fallback path. |
| Audit cleanup affects hot tables | Bounded indexed batches, off-peak schedule, and metrics. |
| Large remediation becomes hard to review | Deliver ordered slices behind stop gates and keep PR status truthful. |

## 10. Definition of done

- Every Gate A-E acceptance item is evidenced.
- All GitHub checks for the final PR SHA are green.
- Full tests run after migrations on PostgreSQL 16.
- Kill-switch queue preservation and fail-closed defaults are proven.
- Untrusted writers are rejected by role-based database authority and Python
  defense in depth.
- Durable attempts converge after crash, timeout, retry, and redelivery.
- Candidate fallback, typed backoff, and owner-safe locks are proven.
- Manual assignment cannot claim false success.
- No unreachable legacy SAT/assignment body remains.
- Retention and readiness gates are operational.
- PR description, `STATUS.md`, `HANDOFF.md`, verification, and rollout
  artifacts match the final code.
- No deployment or production mutation occurs without explicit approval.

## 11. Approval boundary

Felipe must approve this remediation plan before implementation begins.

After approval, implementation starts with DB-02 and OPS-07 only. Work must
stop again before:

- any test using a non-local database;
- any shared-environment migration;
- credential rotation or external infrastructure change;
- staging deployment;
- canary enablement;
- production enforcement.
