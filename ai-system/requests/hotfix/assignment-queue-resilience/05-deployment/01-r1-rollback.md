# R1 — deploy interrompido e rollback

**Data:** 2026-07-23
**Escopo autorizado:** R1, somente API, worker e beat; sem flags, canario ou reconciliacao.

## Deploy observado

- Commit candidato: `3cef51df80f64c1e461bafab8d072cafa49f05d1`.
- API: `3e0532b1-1d07-4e9c-93da-42f20228077a`.
- Worker: `3f8e5f65-1bdc-47ac-9423-e16315afdf03`.
- Beat: `8e65d513-da41-47b5-8b3f-f5a30f6970b7`.
- Os tres deployments chegaram a `SUCCESS`; health HTTP permaneceu 200 e nao havia migration pendente.

## Condicao de parada

Depois da troca do worker, os seis agentes ativos ficaram stale. As tarefas SAT
continuavam consultando 127 usuarios no HubSpot, mas nao chegavam ao evento
`sat_heartbeat_done`.

A causa foi confirmada no contrato persistente: a revisao passou a incrementar
somente em mudanca material, mas uma `AgentAvailabilityDecision` ainda era
inserida em todo heartbeat. Heartbeats identicos repetiam `(agent, revision)` e
violavam `uniq_agent_availability_revision`, revertendo toda a transacao.

## Rollback

O commit estavel `f484f16f5f9838228ffe4039b9f05d1f1cc94acb` foi redeployado nos tres servicos:

- API: `2ce83bfd-af79-4255-bd16-b49c6827aadd`.
- Worker: `ceb109a3-8cf5-43ec-a78a-fe30e5c2e41a`.
- Beat: `f92fcc97-3b6f-4d0f-9ada-79869d94ec96`.

Evidencia pos-rollback:

- health da API: HTTP 200;
- dois heartbeats consecutivos concluiram com `sat_heartbeat_done`;
- agentes ativos: 6; stale acima de 60 segundos: 0;
- fila pending/queued: 0; claims: 0; tentativas nao completed: 0.

Nenhuma fila, tentativa ou historico foi apagado. R2, R3, flags e reconciliacao
nao foram executados.

## Remediacao local

A criacao da decisao de auditoria passou a ocorrer somente quando ha mudanca
material/revisao nova. Heartbeats identicos continuam renovando
`availability_observed_at` sem criar uma decisao duplicada.

Validacao final em PostgreSQL 16 e Redis 7 descartaveis:

- suite completa: 540 passaram, zero falhas e zero skips;
- Ruff check e format check: passaram, 275 arquivos formatados;
- mypy: passou, 271 arquivos;
- Django system check: passou;
- migration check: nenhuma mudanca detectada;
- `git diff --check`: passou.

Uma nova tentativa de R1 permanece condicionada ao merge do PR e a uma nova
aprovacao explicita.
