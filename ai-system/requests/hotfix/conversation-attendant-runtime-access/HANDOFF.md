# Handoff

## Resumo

- Adicionada migration reversível para conceder `SELECT, INSERT, UPDATE` no histórico de atendentes.
- Grants limitados aos papéis JUDAH de produção e staging que existirem.
- RLS, owner, policies e privilégios públicos permanecem inalterados.
- Testes cobrem privilégio mínimo, rollback e ausência dos papéis.

## Arquivos modificados

- `apps/support/migrations/0032_grant_conversation_attendant_runtime_access.py`
- `apps/support/tests/test_conversation_attendant_runtime_grants.py`
- `ai-system/requests/hotfix/conversation-attendant-runtime-access/`

## Como testar localmente

```powershell
$env:DATABASE_URL='sqlite:///./.test-attendant-grants.sqlite3'
$env:PYTEST_ADDOPTS='--no-cov apps/support/tests/test_conversation_attendant_runtime_grants.py apps/support/tests/test_conversation_instance_attendants.py apps/support/tests/test_ticket_lifecycle.py'
.venv\Scripts\python.exe run_tests_local.py

$env:DJANGO_SETTINGS_MODULE='core.settings.test'
$env:DJANGO_SECRET_KEY='local-verification-only'
.venv\Scripts\python.exe -m mypy apps/support/migrations/0032_grant_conversation_attendant_runtime_access.py apps/support/tests/test_conversation_attendant_runtime_grants.py

uv run ruff check apps/support/migrations/0032_grant_conversation_attendant_runtime_access.py apps/support/tests/test_conversation_attendant_runtime_grants.py
```

## Riscos e integração

- SQLite valida a operação como no-op; a semântica real de PostgreSQL deve ser verificada em staging ou banco descartável antes do deploy.
- O deploy deve aplicar a migration com o papel de schema owner, não com o runtime sem autoridade de grant.
- Após staging, verificar `has_table_privilege` para produção/staging e confirmar que `anon`/`authenticated` continuam sem acesso.
- A migration não recupera o ticket 48413609787 nem recria históricos ausentes; recuperação requer autorização e runbook próprios.
