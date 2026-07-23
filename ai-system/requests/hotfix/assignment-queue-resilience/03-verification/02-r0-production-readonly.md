# R0 — baseline read-only de produção

**Data:** 2026-07-23 15:17 -03:00
**Escopo autorizado:** Railway/produção estritamente read-only
**Deploy, flags, drain, backfill, HubSpot write ou DB write executados:** não

## Topologia e versão

- Railway autenticado como workspace Suporte InChurch, projeto JUDAH.
- Ambiente único: `production`.
- Serviços: `judah`, `judah-worker`, `judah-beat` e Redis.
- API, worker e beat: deployments `SUCCESS` e instâncias `RUNNING`.
- Commit comum implantado: `f484f16f5f9838228ffe4039b9f05d1f1cc94acb`.
- O mesmo commit é o `HEAD` base local; o hotfix novo ainda não foi implantado.

## Health e flags

- `/api/v1/health/`: HTTP 200, `alive`.
- `/api/v1/health/ready`: HTTP 200, `healthy`.
- Database, cache, auth schema e JWT mint: `ok`.
- Runtime de atribuição autoritativo: sim.
- `AUTO_ASSIGNMENT_ENABLED=true`.
- `ABSENCE_SAFE_ELIGIBILITY_ENFORCED=true`.
- `CONVERSATION_CYCLES_ENFORCED=false`.

## Banco e protocolo durável

- Vendor: PostgreSQL.
- Migrations pendentes: 0.
- Fila total/pronta: 0/0.
- Claims ativos/expirados: 0/0.
- Poison rows: 0.
- Attempts: 114, todos `completed`.
- Completed attempt com queue row residual: 0.
- `reserved` stuck, `repair_required` e retry devido: 0.
- Agentes elegíveis: 5; observações stale: 0.

## Ciclos

- `assigned`: 7.
- `closed`: 95.
- `queued`: 1.
- `queued_without_dispatch`: 1.
- Projection mismatches: 0.
- Enforcement permanece corretamente desligado porque ainda existem projeções
  legadas e um ciclo queued sem dispatch.

O ciclo isolado não possui linha pronta e não bloqueia o drain atual. Ele deve
permanecer fora do R1 e ser classificado somente no R5 dry-run/reconciliação,
que exige autorização separada.

## Worker, SAT e locks

- Heartbeats SAT contínuos, seis agentes verificados por ciclo e fencing token
  avançando; lease final estava liberado (`active=false`).
- Repair periódico: `scanned=0`, sem failures.
- Drains periódicos: `total_pending=0`, `assigned=0`, `remaining=0`.
- Nenhum log de nível error foi retornado no snapshot de duas horas.
- A versão atual ainda registra `owned_cache_lock_release_deferred_to_ttl` para
  `matchmaker_drain_lock`, comportamento removido/corrigido pelo hotfix.

O Redis privado respondeu `ok` pelo readiness. A inspeção de chaves/TTLs não
foi possível via `railway run` porque ele executa localmente e não resolve
`redis.railway.internal`; o caminho SSH remoto exige chave Railway não
registrada. Nenhuma configuração foi alterada para contornar essa limitação.

## Stop conditions

- `assigned > total_pending`: não observado.
- Repetição/no-progress: não observada no baseline vazio.
- Owner/capacidade divergentes: nenhuma evidência agregada.
- Attempts presos/repair crescente: não.
- Migration/schema divergente: não.
- Worker sem banco/Redis/HubSpot: não; todos os sinais estão operacionais.

## Resultado

R0 aprovado para solicitar R1. A ressalva `queued_without_dispatch=1` permanece
isolada com enforcement desligado e deve ser tratada apenas no R5. R1 continua
dependendo de aprovação explícita do Felipe e deve implantar API, worker e beat
no mesmo commit, sem migration.
