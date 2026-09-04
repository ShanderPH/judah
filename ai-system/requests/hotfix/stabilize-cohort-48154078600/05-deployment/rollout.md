# Rollout — opening cohort barrier

## R0/R1

Após autorização, confirmar read-only SHA API/worker/beat, migrations, roles/RLS, SAT, fila, provider e baseline.
No R1, API primeiro com predeploy/`0030`, depois worker e beat no mesmo SHA, mantendo
`OPENING_COHORT_BARRIER_MODE=off`.

## R2/R3

Shadow exige aprovação própria e no mínimo três aberturas representativas. Enforcement exige nova aprovação e
acompanhamento até deadline + dois drains. Nunca executar replay ou reassignment como parte deste rollout.

## Rollback

O kill switch é `OPENING_COHORT_BARRIER_MODE=off`, separado de `AUTO_ASSIGNMENT_ENABLED`. Voltar para off em
caso de coorte além do deadline, claim/attempt durante defer, bloqueio pós-abertura, duplicate effect,
divergência de capacidade/RLS ou p95 acima do budget. Rollback de código/migration e recuperação de fila são
operações separadas.
