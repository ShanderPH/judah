# Handoff

## Resumo do implementado/corrigido

- Identificada staging como o segundo writer que restaurava Nathan para
  `online`; após o shutdown de staging, o flapping cessou sem desabilitar o
  agente.
- Criada conciliação autoritativa e idempotente a partir da HubSpot Users API,
  incluindo ausência, horário individual, timezone, estabilidade e freshness.
- Adicionadas cercas de ambiente no Python e PostgreSQL para staging não
  alterar disponibilidade, capacidade, fila ou atribuições de produção.
- Adicionadas auditoria por revisão, lease com owner token/fencing e guarda
  final do Matchmaker sob lock.
- Removida a edição de status pela API/Admin e eliminado o falso contrato de
  `contact.propertyChange/hs_availability_status`, que a HubSpot não oferece.
- O webhook real de ticket NOVO agora enfileira, força uma releitura sem cache
  da Users API e falha fechado antes de chamar o Matchmaker.
- O candidato escolhido é consultado novamente pelo ID na Users API,
  imediatamente antes da reserva; `away`, ausência, dado inválido ou falha
  remota vetam a atribuição sem modificar o snapshot SAT.

## Arquivos modificados

- `apps/integrations/hubspot/client.py`
- `apps/integrations/hubspot/user_availability.py`
- `apps/support/availability_runtime.py`
- `apps/support/eligibility_service.py`
- `apps/support/sat_service.py`
- `apps/support/queue_service.py`
- `apps/support/matchmaker_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/tasks.py`
- `apps/support/agent_sync_service.py`
- `apps/support/models.py`
- `apps/support/admin.py`
- `apps/support/admin_api.py`
- `apps/support/schemas.py`
- `apps/support/migrations/0015_absence_safe_eligibility.py`
- `apps/support/migrations/0016_block_non_authoritative_runtime_writes.py`
- `core/settings/base.py`
- `core/settings/production.py`
- `apps/health/api.py`
- testes correspondentes em `apps/support/tests/` e
  `apps/integrations/tests/`.

## Como testar localmente

```powershell
uv run ruff check .
$env:DJANGO_ENV='test'
$env:DJANGO_SECRET_KEY='local-test-only'
$env:DATABASE_URL='sqlite:///./.test.sqlite3'
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
uv run python run_tests_local.py
```

## Riscos conhecidos / áreas frágeis

- O formato real das propriedades de todos os usuários HubSpot deve ser
  observado em shadow antes da enforcement; dado malformado falha fechado.
- A migration `0016` usa triggers PostgreSQL e ainda precisa de validação em
  staging isolado antes de produção.
- A CLI Railway local não está autenticada nesta sessão, portanto variáveis e
  topologia atuais não foram alteradas.
- Staging deve receber banco e Redis próprios mesmo com as cercas adicionadas.

## Pontos de integração críticos

- Aplicar `0015` antes de `0016`.
- Confirmar na readiness que apenas produção é writer autoritativo.
- Manter Nathan com `auto_assign_enabled=true`.
- Comparar decisões shadow por um dia antes de habilitar
  `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=true`.
- Confirmar em staging que a credencial possui `crm.objects.users.read` para a
  leitura individual executada pela guarda final.
- Não aplicar migrations, deploy ou enforcement sem aprovação explícita.
