# Handoff

## Resumo

- Corrigida a conversão de timestamps de estágio ISO-8601 na fronteira HubSpot CRM para `datetime` UTC aware.
- Consumidores internos usam o instante normalizado na decisão de reabertura, na abertura de ciclo e no fechamento por observação de owner.
- Webhook segue estrito para epoch-ms; nenhum reparo histórico foi executado.
- Teste integrado reproduz os horários reais e verifica a materialização e a idempotência.

## Arquivos modificados

- `apps/integrations/hubspot/client.py`
- `apps/support/auto_assign_service.py`
- `apps/support/conversation_cycle_service.py`
- `apps/support/ticket_close_service.py`
- `apps/integrations/hubspot/tests/test_crm_stage_timestamps.py`
- `apps/support/tests/test_ticket_close_service.py`
- `ai-system/requests/hotfix/hubspot-crm-stage-timestamps/`

## Como testar

No checkout do hotfix, com Python 3.14 e dependências instaladas:

```bash
ruff check .
ruff format --check .
DJANGO_ENV=test DJANGO_SECRET_KEY=test DATABASE_URL=sqlite:///./.test.sqlite3 mypy apps core common
python run_tests_local.py
DJANGO_ENV=test DJANGO_SECRET_KEY=test DATABASE_URL=sqlite:///./.test.sqlite3 python manage.py makemigrations --check --dry-run
git diff --check
```

## Riscos e VERIFY

- Entradas CRM presentes sem timezone ou malformadas agora falham na fronteira; isso conserva o estado e exige investigação/retry em vez de liberar occupancy com identidade incerta.
- Primeiro verificar em produção a ocorrência real aplicada e, em seguida, a consulta read-only de divergências novas. O gate de produção permanece aberto até ambos passarem.
