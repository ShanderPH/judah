request: hotfix/manual-owner-accounting
cycle: M
state: REVIEW
opened_at: 2026-09-22T23:00:00-03:00
last_update: 2026-09-22T23:50:00-03:00
agent_run_id: codex-root
current_blockers: []
next_action: "Criar commit e PR; Felipe realiza deploy e confirma smoke antes do enforce"
artifacts_generated:
  - 00-context/production-diagnosis.md
  - 01-plan/master-plan.md
  - 03-verification/verification-report.md
  - HANDOFF.md
verification_runs: 7

watch_list:
  - apps/support/tasks.py
  - apps/support/tests/test_manual_assignment_capacity.py
  - apps/support/tests/test_ticket_lifecycle.py

implementation_tasks:
  BE-01: concluida
  BE-02: concluida
  BE-03: concluida
  BE-04: concluida
  V-01: concluida
  V-02: concluida
  OPS-01: preparado_nao_executado

external_gates: "Deploy e smoke pelo usuario; OPENING_COHORT_BARRIER_MODE=enforce somente apos confirmacao explicita."
final_verification: "863 passed, 43 skipped; support 420 passed, 38 skipped; ruff clean; mypy 355 files clean; no migration drift"
