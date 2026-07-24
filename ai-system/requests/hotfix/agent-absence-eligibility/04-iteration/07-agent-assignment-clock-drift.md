# Iteration 07 — agent assignment clock drift

Date: 2026-07-21

## Production diagnosis

- Six active agents had `agents.last_assignment_at` in the future.
- `assignment_logs.assigned_at` contained no future assignments and remained the
  reliable source for the last completed assignment.
- Production stores `agents.last_assignment_at` as `timestamp without time
  zone`, while Django runs with `USE_TZ=True` and `America/Sao_Paulo`.
- `sat_heartbeat()` loaded every active agent and called `agent.save()` without
  `update_fields`, rewriting routing fields that SAT does not own.
- Each heartbeat advanced the naive assignment timestamp by three hours. After
  the first data repair, every active agent accumulated exactly 39 hours of
  drift again, proving the recurrence.

## Immediate production work

- Restored the six timestamps once from the latest non-future
  `assignment_logs.assigned_at` value.
- Verified zero future timestamps and a correct fair-queue order immediately
  after the update.
- The values initially drifted again because the deployed heartbeat still
  performs full model saves.
- The Railway runtime could not alter the schema because `agents` is owned by
  `postgres`; its attempted transaction was fully rolled back.
- After Supabase MCP authentication, an administrative migration converted the
  column to `timestamp with time zone`. The dependent
  `v_agent_performance_realtime` view was dropped and recreated atomically with
  its definition, owner, `security_invoker`, comment, and grants preserved.
- The seven agent rows were then restored from their latest completed
  assignment logs through the authoritative JUDAH runtime.
- After more than two SAT cycles, all six active agents remained eligible,
  no timestamp was in the future, and no three-hour drift recurred.

## Repository fix

- SAT now saves an explicit allowlist of availability-owned fields and cannot
  rewrite `last_assignment_at`, chat counters, assignment totals, or unrelated
  routing state.
- Regression coverage asserts that a heartbeat preserves the assignment clock
  and always supplies `update_fields` to `Agent.save()`.
- Migration `support.0019` idempotently converts `last_assignment_at` to
  `timestamp with time zone`, interpreting the legacy values as UTC. Its reverse
  converts back to a UTC-naive representation.

## Required rollout order

1. Publish, review, and deploy this hotfix so the SAT field allowlist becomes
   active and Django records `support.0019` as applied. The migration is a no-op
   when the production column is already timezone-aware.
2. Investigate duplicate queue admission separately: ticket `46934213935` had
   an earlier completed assignment for Esther and was later assigned externally
   to Raphael, leaving a second attempt in `external_applied` because the
   completed-ticket uniqueness constraint rejected finalization.
3. Repair the periodic assignment-attempt task, which currently aborts its
   whole batch on the first duplicate completed ticket.

## Verification

- Full isolated SQLite suite: `435 passed, 3 skipped`.
- Coverage: `64.77%` (required: `50%`).
- Ruff check: clean.
- Ruff format check: clean.
- `git diff --check`: clean.
- Mypy: blocked before analysis by the existing
  `NewSemanalDjangoPlugin` internal error in mypy `2.1.0`.
