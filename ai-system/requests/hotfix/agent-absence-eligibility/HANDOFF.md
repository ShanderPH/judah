# Handoff — PR 75 remediation Gates C, D e E

## Resumo do implementado/corrigido

- Protocolo durável reserve/apply/finalize/compensate com reparo após crash.
- Claims PostgreSQL e capacidade serializada; Redis é somente otimização segura.
- HubSpot Users API com falhas tipadas, retry limitado e fail-closed.
- Caminhos legados inalcançáveis removidos; Matchmaker é o entrypoint canônico.
- Readiness, retenção, comando de reparo e suíte PostgreSQL completa adicionados.
- Gate E aprovado no SHA de implementação
  `3bbc0649ed7249a163de7a11ad498cc25ec552fe`: 427 testes locais e hospedados,
  checks GitHub verdes e concorrência/crash repetidos três vezes.

## Arquivos modificados

- `apps/support/durable_assignment_service.py`
- `apps/support/assignment_readiness.py`
- `apps/support/owned_cache_lock.py`
- `apps/support/models.py`
- `apps/support/migrations/0017_durable_assignment_protocol.py`
- `apps/support/matchmaker_service.py`
- `apps/support/sat_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/tasks.py`
- `apps/support/admin_api.py`
- `apps/integrations/hubspot/client.py`
- `apps/integrations/hubspot/exceptions.py`
- `core/settings/base.py`
- testes e artefatos associados em `apps/**/tests/` e `ai-system/...`.

## Como testar localmente

Use somente PostgreSQL local descartável:

```powershell
$env:DJANGO_ENV='test'
$env:DJANGO_SETTINGS_MODULE='core.settings.test'
$env:DJANGO_SECRET_KEY='test-only'
$env:DATABASE_URL='postgresql://judah:judah_dev_password@localhost:5432/judah_test'
$env:OPENAI_API_KEY='test-only'
$env:HUBSPOT_ACCESS_TOKEN='test-only'

.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
uv run ruff check .
uv run ruff format --check .
.venv\Scripts\python.exe -m mypy .
.venv\Scripts\python.exe manage.py check --fail-level WARNING
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
```

## Riscos conhecidos / áreas frágeis

- Roles, grants, credenciais, flags, migration e deploy compartilhados continuam
  bloqueados por OPS-09 e exigem aprovação separada.
- Tentativas `repair_required` impedem sucesso presumido e exigem convergência
  pelo worker/comando antes de intervenção operacional.
- A PR permanece bloqueada somente por revisão obrigatória; o Gate F e qualquer
  rollout continuam fora do escopo até aprovação explícita do Felipe.

## Pontos de integração críticos

- Aplicar `support.0017` antes de habilitar a atribuição.
- Manter `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=true` antes de canário.
- Validar role/application name no readiness após deploy.
- Monitorar tentativas travadas e executar `repair_assignment_attempts` se necessário.
