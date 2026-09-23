request: hotfix/capacity-reconciliation-convergence
cycle: M
state: REVIEW
opened_at: 2026-09-23T00:00:00-03:00
last_update: 2026-09-23T03:55:03-03:00
agent_run_id: codex-root
current_blockers: []
next_action: "Felipe: revisar a PR, fazer merge/deploy e autorizar os gates de produção"
artifacts_generated:
  - 00-context/production-diagnosis.md
  - 01-plan/master-plan.md
  - 03-verification/verification-report.md
  - 05-deployment/rollout.md
  - HANDOFF.md
verification_runs: 6

watch_list:
  - apps/support/durable_assignment_service.py
  - apps/support/owner_reconciliation_service.py
  - apps/support/tests/test_durable_assignment_protocol.py
  - apps/support/tests/test_manual_assignment_capacity.py

implementation_tasks:
  BE-01: concluida
  BE-02: concluida
  BE-03: concluida
  V-01: concluida
  V-02: concluida

external_gates: "Deploy pelo usuario; repair + bootstrap + readiness antes de SUPPORT_CAPACITY_MODE=enforce."
final_verification: "866 passed, 43 skipped; PostgreSQL 11 passed; ruff clean; mypy 355 files clean; no migration drift"
