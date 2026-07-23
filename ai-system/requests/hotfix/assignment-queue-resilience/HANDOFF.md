# HANDOFF — assignment queue resilience

## Resumo do implementado/corrigido

- Outcomes tipados por item com identidade da fila/ciclo, progresso e efeito externo.
- Drain limitado com IDs vistos, contadores separados e isolamento de itens problemáticos.
- Convergência de tentativa completed do mesmo ciclo sem novo owner update e quarentena segura de legado ambíguo.
- Revisão de disponibilidade somente por mudança material e drain concorrente serializado no PostgreSQL.
- Owner manual converge fila/ciclo e compensa tentativa viva sem duplicar capacidade.
- Locks Redis usam cliente redis-py dedicado e Lua compare-and-delete por token.
- Readiness e runbook expõem profundidade, idade, poison rows, conflitos e claims expirados.

## Arquivos modificados

- `apps/support/assignment_readiness.py`
- `apps/support/durable_assignment_service.py`
- `apps/support/matchmaker_service.py`
- `apps/support/owned_cache_lock.py`
- `apps/support/sat_service.py`
- `apps/support/tasks.py`
- `apps/support/tests/test_durable_assignment_protocol.py`
- `apps/support/tests/test_owned_cache_lock.py`
- `apps/support/tests/test_sat_matchmaker.py`
- `apps/support/tests/test_ticket_lifecycle.py`
- `docs/operations/absence-safe-assignment.md`
- `ai-system/requests/hotfix/assignment-queue-resilience/STATUS.md`
- `ai-system/requests/hotfix/assignment-queue-resilience/HANDOFF.md`
- `ai-system/requests/hotfix/assignment-queue-resilience/03-verification/01-postgres16-redis7-gates.md`

## Como testar localmente

Configure apenas serviços locais descartáveis: PostgreSQL 16 em `localhost`,
Redis 7 local e `JUDAH_TEST_REDIS_URL` para um DB Redis de teste. Nunca use
host remoto.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy apps common core
uv run pytest -q
uv run python manage.py check --fail-level WARNING
uv run python manage.py makemigrations --check --dry-run
git diff --check
```

## Verificação executada

- `ruff check .`: passou.
- `ruff format --check .`: passou, 275 arquivos.
- `mypy apps common core`: passou, 271 arquivos.
- `pytest -q` em PostgreSQL 16 + Redis 7: 540 passaram, zero skips.
- V-03: dois workers/uma reserva e disputa pela última capacidade passaram.
- V-06: compare-delete, token alheio e TTL de crash passaram contra Redis real.
- Owner manual × tentativa viva: capacidade final única e tentativa compensada.
- `manage.py check --fail-level WARNING`: passou.
- `makemigrations --check --dry-run`: nenhuma mudança detectada.
- `git diff --check`: passou.

## Riscos conhecidos / áreas frágeis

- O comportamento operacional ainda precisa ser observado no canário autorizado.
- A reconciliação dos ciclos históricos requer dry-run e autorização separados.
- Deploy, canário, enforcement e qualquer write de produção não estão autorizados.

## Pontos de integração críticos para DEPLOY

1. R0 read-only concluído: fila/claims/repairs zerados, migrations em dia e serviços saudáveis.
2. Observar `queued_without_dispatch=1`; manter enforcement desligado e tratar somente no R5 autorizado.
3. Confirmar API, Worker e Beat no mesmo commit novo durante R1.
4. Observar owner/capacidade reais e interromper diante das stop conditions do plano.
5. Manter reconciliação histórica e qualquer write em aprovação separada.
