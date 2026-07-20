request: hotfix/agent-absence-eligibility
cycle: F
state: IMPLEMENT
opened_at: 2026-07-17T15:24:48-03:00
last_update: 2026-07-20T15:58:54-03:00
agent_run_id: codex-root
current_blockers:
  - "PR 75 must not merge until the new-ticket-only rollout gate is committed, pushed, and green."
next_action: "Codex: publish migration 0018 and the persistent new-ticket assignment gate to PR 75; Felipe merges only after final green checks."
artifacts_generated:
  - 00-context/production-diagnosis.md
  - 00-context/ops-prerequisite-revalidation.md
  - 00-context/research.md
  - 01-plan/master-plan.md
  - 01-plan/pr75-remediation-plan.md
  - 02-artifacts/backend/01-absence-safe-eligibility.md
  - 02-artifacts/backend/09-queue-safe-runtime-capabilities.md
  - 02-artifacts/database/02-repair-runtime-guard-migration.md
  - 02-artifacts/database/03-role-based-writer-isolation.md
  - 02-artifacts/devops/07-postgres-ci-gate.md
  - 03-verification/01-local-verification.md
  - 03-verification/02-pr75-gate-a.md
  - 03-verification/03-pr75-gate-b.md
  - 03-verification/04-pr75-gates-c-d-e.md
  - 03-verification/05-pr75-gate-f-new-ticket-boundary.md
  - 05-deployment/rollout.md
  - HANDOFF.md
verification_runs: 81
