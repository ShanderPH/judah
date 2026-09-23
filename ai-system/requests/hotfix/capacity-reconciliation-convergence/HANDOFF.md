# Handoff

## Resumo do implementado/corrigido

- Tentativas já compensadas e ligadas a ciclo encerrado agora convergem para `compensated`.
- O reparador não encerra apenas pela contagem `skipped_stale_cycle`; ele persiste a transição.
- O histórico de capacidade passa a avançar em lotes retomáveis e não relê terminais confirmados.
- Tickets ativos no HubSpot e reservas mantidas têm prioridade e continuam fail-closed.
- O bootstrap explícito não é interrompido pelo prazo curto do refresh online.

## Arquivos modificados

- `apps/support/durable_assignment_service.py`
- `apps/support/owner_reconciliation_service.py`
- `apps/support/management/commands/bootstrap_support_capacity.py`
- `apps/support/tests/test_durable_assignment_protocol.py`
- `apps/support/tests/test_manual_assignment_capacity.py`
- `ai-system/requests/hotfix/capacity-reconciliation-convergence/`

## Como testar localmente

```bash
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/judah-tribe-uv-cache uv run mypy apps core common
python run_tests_local.py
```

Para validar locks e concorrência, executar os três testes novos junto de
`apps/support/tests/test_capacity_postgres.py` contra um PostgreSQL 16 local descartável.

## Riscos conhecidos / áreas frágeis

- O bootstrap ainda falha de forma segura se o portfólio ativo mais as reservas excederem `SUPPORT_CAPACITY_MAX_SCAN_TICKETS`.
- Uma falha individual do HubSpot degrada o agente e exige nova execução; nenhuma ausência é inferida de busca incompleta.
- O tempo total do bootstrap explícito cresce com o histórico, limitado pela quantidade configurada de identidades e pelos timeouts de cada chamada.

## Pontos de integração críticos

- Busca completa de tickets ativos por owner no HubSpot.
- Revisão de geração (`capacity_revision`) durante o scan.
- Conclusão idempotente de `AgentCapacityReservation`.
- Freshness de `capacity_reconciled_at` antes do enforce.
