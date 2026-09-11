request: hotfix/conversation-attendant-runtime-access
cycle: M
state: DEPLOY
opened_at: 2026-09-09T09:23:53-03:00
last_update: 2026-09-11T10:47:45-03:00
agent_run_id: /root
current_blockers: []
next_action: "Publicar a migration 0032, aplicar em producao e verificar privilegios antes do bootstrap."
artifacts_generated:
  - 00-context/production-diagnosis.md
  - 02-artifacts/database/DB-01-runtime-grant.md
  - 03-verification/01-local-results.md
  - 05-deployment/01-rollout-and-rollback.md
  - HANDOFF.md
verification_runs: 2

watch_list:
  - apps/support/migrations/0032_grant_conversation_attendant_runtime_access.py
  - apps/support/tests/test_conversation_attendant_runtime_grants.py

completion_scope: implementacao_e_verificacao_locais
final_verification: "24 passed; ruff clean; mypy clean; makemigrations check clean; git diff check clean"
external_gates: "Usuario autorizou publicacao, deploy, bootstrap e alteracao sequencial das flags em 2026-09-11."
