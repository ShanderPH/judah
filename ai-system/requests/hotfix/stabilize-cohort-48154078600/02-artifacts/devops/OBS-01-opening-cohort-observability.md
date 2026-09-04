# OBS-01 — observabilidade da barreira de abertura

## Métricas implementadas

- `assignment_cohort_barrier_started_total{mode}`
- `assignment_cohort_barrier_released_total{reason}`
- `assignment_cohort_barrier_duration_seconds{reason}`
- `assignment_cohort_initial_eligible` / `initial_stabilizing`
- `assignment_cohort_final_eligible` / `final_stabilizing`
- `assignment_cohort_protected_backlog`
- `assignment_cohort_callbacks_total{result}`
- `assignment_cohort_beat_fallback_total`
- `assignment_cohort_active{mode}`

Os labels são limitados a modo, reason e result. Nomes, e-mails, ticket IDs, payloads e secrets não são
emitidos pelo serviço.

## Readiness e dashboards para R0/R2

O snapshot inclui modo, migration, coorte ativa, idade, deadline vencido e backlog deferido. Medir p50/p95/p99
abertura→primeiro attempt, duração/tamanho/release reason, concentração das primeiras atribuições, mudanças de
owner em 2/5 min e callbacks bloqueados/falhos. Nenhum dashboard foi criado em produção nesta request.
