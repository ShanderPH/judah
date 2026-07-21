# Gate D verification

**Data:** 2026-07-21
**Banco:** SQLite local descartavel via `run_tests_local.py`.

| Prova | Resultado |
|---|---|
| Suite local completa | 520 passed, 5 skipped |
| Cobertura | 66.00%, minimo 50% atingido |
| Ruff check `apps/support` | limpo |
| Ruff format `apps/support` | 73 arquivos formatados |
| `git diff --check` | limpo |
| mypy | erro interno do plugin `NewSemanalDjangoPlugin` no mypy 2.1.0 |

Dois ciclos preservam dois fechamentos; owner change antigo nao altera o ciclo
corrente; item venenoso nao bloqueia o lote; metricas e APIs sao cycle-aware.
PostgreSQL 16, Gate E, backfill, deploy e mutacoes externas nao foram executados.
