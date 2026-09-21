# HANDOFF — shadow cohort lifecycle

## Resumo do implementado

- Finalização idempotente e transacional da coorte, independente de linha na fila.
- Callback finaliza após o refresh SAT e só então chama o drain canônico.
- Fallback do Beat fecha coortes expiradas antes do retorno rápido por fila vazia.
- Readiness separa a coorte da janela atual de resíduos ativos expirados.
- Quatro regressões cobrem o incidente, o fallback, a autoridade do runtime e a seleção do readiness.

## Arquivos modificados

- `apps/support/opening_cohort_service.py`
- `apps/support/tasks.py`
- `apps/support/assignment_readiness.py`
- `apps/support/tests/test_opening_cohort_barrier.py`

## Como testar localmente

```bash
DJANGO_ENV=test DATABASE_URL=sqlite:///./.test.sqlite3 DJANGO_SECRET_KEY=test-only \
  .venv/bin/python -m pytest apps/support/tests/ -q
.venv/bin/python -m ruff check apps/support/opening_cohort_service.py apps/support/tasks.py \
  apps/support/assignment_readiness.py apps/support/tests/test_opening_cohort_barrier.py --no-cache
.venv/bin/python -m mypy apps/support/opening_cohort_service.py apps/support/tasks.py \
  apps/support/assignment_readiness.py
```

## Riscos conhecidos / áreas frágeis

- As cinco coortes históricas continuam exigindo reconciliação operacional autorizada após o deploy.
- O rollout para `enforce` continua bloqueado pelos demais gates de readiness/capacidade já diagnosticados.
- A prova local usa SQLite; locking concorrente PostgreSQL permanece coberto pela suíte de integração existente.

## Pontos de integração críticos

- VERIFY deve confirmar que a finalização ocorre antes do early return e permanece idempotente sob callback + Beat.
- VERIFY deve conferir que nenhuma alteração atingiu os arquivos preexistentes do webapp/docker-compose.
