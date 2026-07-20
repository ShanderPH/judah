# Handoff — PR 75 remediation Gate B

## Resumo do implementado/corrigido

- Separadas as capacidades de ingestão, reconciliação e atribuição; desligar
  auto-assignment preserva webhook intake, fila e backfill.
- `AUTO_ASSIGNMENT_ENABLED` agora falha fechado por padrão; shadow e canário
  não podem cair na elegibilidade legada.
- Adicionado canário por UUID local de agente, com configuração inválida
  falhando fechado.
- `support.0016` passou a autorizar writers por roles PostgreSQL explícitos,
  cobrindo insert/update/delete nas tabelas de roteamento.
- Guardas Python agora vetam reconciliadores, lifecycle, Django Admin e
  operações manuais antes de I/O; Railway pre-deploy preserva a fila.

## Arquivos modificados

- `apps/support/availability_runtime.py`
- `apps/support/tasks.py`
- `apps/support/matchmaker_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/queue_service.py`
- `apps/support/sat_service.py`
- `apps/support/admin.py`
- `apps/support/admin_api.py`
- `apps/support/management/commands/railway_predeploy.py`
- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py`
- `apps/support/tests/test_gate_b_runtime_controls.py`
- `apps/support/tests/test_runtime_guard_migration.py`
- `apps/support/tests/test_railway_predeploy.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `core/settings/base.py`
- `core/settings/development.py`
- `core/settings/production.py`
- `core/settings/test.py`
- `ai-system/requests/hotfix/agent-absence-eligibility/02-artifacts/backend/09-queue-safe-runtime-capabilities.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/02-artifacts/database/03-role-based-writer-isolation.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/03-verification/03-pr75-gate-b.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/05-deployment/rollout.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/STATUS.md`
- `ai-system/requests/hotfix/agent-absence-eligibility/HANDOFF.md`

## Como testar localmente

Use apenas PostgreSQL 16 e Redis locais descartáveis. O database informado a
pytest deve começar com `judah_test`.

```powershell
$env:DJANGO_ENV='test'
$env:DJANGO_SECRET_KEY='local-test-only'
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/judah_test'
$env:REDIS_URL='redis://127.0.0.1:56379/0'

uv run python -m common.database_safety
uv run python manage.py migrate --run-syncdb
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
git diff --check
```

## Riscos conhecidos / áreas frágeis

- Os roles e grants compartilhados ainda não existem; OPS-09 exige aprovação
  explícita, isolamento de staging e possível rotação de credenciais.
- O protocolo durável contra crash entre reserva, HubSpot e finalize pertence
  ao Gate C e ainda não foi implementado.
- A implementação legada inalcançável permanece até o Gate D; seus entrypoints
  ativos já estão protegidos pelas capacidades do Gate B.
- Nenhuma migration compartilhada, alteração de credencial/flag ou deploy foi
  executado; os Gates A e B foram preparados para publicação na PR 75.

## Pontos de integração críticos

- VERIFY deve manter a prova de que `application_name` forjado não eleva role.
- O futuro `AssignmentAttempt` deve receber o mesmo trigger role-based.
- Shadow obrigatório: assignment off, ingestão/reconciliação on.
- Canary obrigatório: eligibility enforced e allowlist de `Agent.id` UUID.
- Não avançar para Gate C sem a próxima autorização prevista no plano.
