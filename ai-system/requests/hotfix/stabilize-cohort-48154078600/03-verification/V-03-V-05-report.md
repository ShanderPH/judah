# V-03 a V-05 — relatório de verificação

| Gate | Ambiente | Resultado |
|---|---|---|
| V-01/V-02 | SQLite local privado | 14 passed, 1 integração skipped; módulo novo 93,38% |
| V-03 | PostgreSQL 16 descartável | concorrência + migration/RLS/grants passaram |
| V-04 | PostgreSQL 16 + Redis 8.6 + worker Celery real | ETA, lease, capacidade, restart/handoff e redelivery passaram |
| V-05 suíte | SQLite local privado | 782 passed, 34 skipped; cobertura global 90,35% |
| Ruff / mypy / migration drift / diff | local | todos limpos |

Foram provados defer antes de claim/attempt, gate comum single+drain, bypass pós-abertura, coorte/deadline
imutáveis, all-settled/deadline, callback pós-commit, rollback/falha de broker, locking PostgreSQL e telemetria
sem PII. Os contêineres descartáveis foram removidos. R0/R1/R2/R3 não foram executados.
