# Handoff — queue-status schema contract

## Resumo

- Branch sincronizada com a `main` no merge do PR #93 (`9dd4bd4`); removida a
  migration `0024` concorrente e reaproveitada a migration consolidada do PR.

- Adicionada migration PostgreSQL explícita, idempotente e reversível para o
  domínio `pending`, `queued`, `failed`, com validação via catálogo.
- Rollback falha fechado quando existem linhas `failed`.
- Preservada a correção de collision/savepoint já entregue pelo PR #92; o patch
  duplicado e seu teste acoplado ao método privado foram removidos.
- Adicionadas regressões de contrato de migration e drain após quarentena de
  legado ambíguo.
- Fixado o contrato compartilhado `agno==2.8.5` / `mcp==1.28.1` para instalações
  locais, CI e todas as imagens Docker.
- Atualizados modelos, autoridade de migrations e runbook.

## Arquivos modificados

- `apps/support/migrations/0024_repair_queue_status_constraint.py` (herdada do PR #93;
  validada pela cobertura complementar deste hotfix)
- `apps/support/tests/test_queue_status_schema_contract_migration.py`
- `apps/support/tests/test_sat_matchmaker.py`
- `docs/database/models.md`
- `docs/database/migrations.md`
- `requirements/constraints.txt`
- `requirements/base.txt`
- `.github/workflows/ci.yml`
- `.dockerignore`
- `Dockerfile`
- `Dockerfile.worker`
- `Dockerfile.beat`
- `ai-system/requests/hotfix/queue-status-schema-contract/`

## Como testar

```powershell
.venv\Scripts\python.exe run_tests_local.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe apps common core
.venv\Scripts\python.exe run_checks.py
git diff --check
```

Para a lane PostgreSQL, configurar `JUDAH_TEST_DATABASE_URL` exclusivamente para
um PostgreSQL local descartável e executar o runner. Ele recusa hosts remotos.

## Riscos e áreas frágeis

- Produção usa PostgreSQL 17.6, enquanto a documentação do workspace cita 16.
- Railway CLI não está autenticado nesta sessão.
- O `collectstatic` do Dockerfile ainda mascara ausência de `debug_toolbar` com
  o fallback preexistente `|| mkdir`; os builds concluem, mas esse hardening não
  pertence ao contrato Agno/MCP deste hotfix.

## Primeira matriz do VERIFY

1. Logs brutos do novo CI confirmando o passo de contrato Agno/MCP.
2. Exclusão de drift não relacionado antes do PR.
3. `pg_get_constraintdef` após deploy autorizado.
4. Smoke operacional pós-deploy separado.
