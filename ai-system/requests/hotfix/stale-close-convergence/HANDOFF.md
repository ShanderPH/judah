# Handoff — convergência de fechamentos

- Ocorrências calculadas de FECHADO usam a policy idempotente e adiam a transição do lifecycle para a resolução do ciclo.
- O serviço resolve o ciclo pelo timestamp, valida o provider fora dos locks e materializa somente projeções desse ciclo.
- O reconciliador reutiliza o snapshot; o dispatcher permite retry de ocorrências stale PENDING/FAILED.
- O reparador é limitado e dry-run por padrão; apply exige writer authority.

## Arquivos de produção

Relativos à raiz `/home/felipe-teixeira/.codex/worktrees/afa0/judah`:

- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/services/service_cycles.py` (propagação pontual de occurrence time)
- `apps/support/ticket_close_service.py`
- `apps/support/auto_assign_service.py`
- `apps/support/owner_reconciliation_service.py`
- `apps/support/management/commands/reconcile_ticket_closures.py`
- `apps/webhooks/services.py` (ajuste pontual comprovado por teste)
- `apps/webhooks/handlers/hubspot_handler.py` e `apps/support/tasks.py` (propagação pontual do ID da ocorrência para logs)

## Validação local

```bash
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run mypy apps core common
.venv/bin/python run_tests_local.py
JUDAH_TEST_DATABASE_URL="$JUDAH_LOCAL_TEST_DATABASE_URL" PYTEST_ADDOPTS='-k test_postgres_concurrent_close_converges --no-cov' .venv/bin/python run_tests_local.py
```

Configure `JUDAH_LOCAL_TEST_DATABASE_URL` para um banco PostgreSQL local descartável conforme o compose do projeto. O runner rejeita bancos remotos.

## Riscos e pontos prioritários

- Decisão de domínio pendente para ciclo já CLOSED cuja ClosedConversation está ausente; ver master-plan.
- Conferir reabertura concorrente, integridade de timestamp e capacidade nos três modos.
- Conflitos de revisão do provider seguem retry da task; classificações de domínio não geram retry infinito.
- Nenhum deploy, provider read de produção ou repair operacional autorizado/executado nesta etapa.
