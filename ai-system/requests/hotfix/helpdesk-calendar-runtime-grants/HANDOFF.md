# Hotfix: permissões runtime do calendário

## Resumo

- Corrige o `500 permission denied for table helpdesk_schedules` observado após o PR #106.
- Concede CRUD mínimo às roles runtime nas quatro tabelas nativas do calendário.
- Mantém credenciais de schema e runtime separadas.
- Inclui reversão explícita e testes de regressão do SQL gerado.

## Arquivos modificados

- `apps/support/migrations/0029_grant_helpdesk_calendar_runtime_access.py`
- `apps/support/tests/test_helpdesk_calendar_runtime_grants.py`

## Como testar

```powershell
.venv\Scripts\python.exe run_tests_local.py apps/support/tests/test_helpdesk_calendar_runtime_grants.py
.venv\Scripts\python.exe run_tests_local.py apps/support/tests/test_helpdesk_calendar.py
```

## Riscos e integração

- A migration depende da `support.0028` e só atua em PostgreSQL.
- Roles inexistentes são ignoradas para preservar ambientes locais.
- Após o deploy, validar `GET /api/v1/support/helpdesk-calendar/` autenticado e a ausência de novos eventos `helpdesk_calendar_runtime_fallback`.

## Verificação local

- Ruff check e format: aprovado.
- Pytest local isolado: `1082 passed, 12 skipped`; cobertura `90,07%`.
- `git diff --check`: aprovado.
- Mypy 2.1.0: bloqueado por erro interno ao construir `NewSemanalDjangoPlugin`, antes da análise dos arquivos.
