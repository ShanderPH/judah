# ARCH-01 — Mapa de escrita do domínio HubSpot / Support

Base: `main` local em `62fb21518cd0c0726c80a1050927b268a708912d`, inspecionada em 2026-09-28. Este é o inventário para implementação; os writers únicos propostos ainda não foram implantados.

## Autoridade dos fatos e caminhos live

| Fato, entrada e leitura | Escrita atual | Classificação | Destino |
|---|---|---|---|
| Webhook de entrada em NOVO → `hubspot_handler._handle_ticket_entered_novo` → `task_matchmaker_assign_single` → leitura CRM | `matchmaker_service.enqueue_new_ticket` chama `conversation_cycle_service.open_or_get_cycle` e cria `NewConversation` | migrate-to-canonical | `lifecycle_occurrence_service` persiste ocorrência comprovada `entered_support_queue` e delega admissão a `open_or_get_cycle`. A projeção de fila permanece em Support, preservando elegibilidade e fencing. |
| Webhook `hs_pipeline_stage` em NOVO | `hubspot_handler._handle_pipeline_stage_change` passa `occurredAt` como identidade de entrada | remove | Despachar readback sem usar o horário do evento como entrada no estágio. Só propriedade de entrada comprovada abre ciclo. |
| Webhook de owner → `task_handle_owner_change` → readback CRM | `owner_reconciliation_service.reconcile_ticket` abre ciclo com `entered_novo_at` do snapshot; `_project_owner` escreve assignment e `AssignmentLog` | migrate-to-canonical | Persistir evidência de entrada pelo occurrence service antes de projetar. Reconciliação de owner escreve occupancy, sem criar identidade de ciclo. |
| Webhook de owner em modos `off`/`shadow` | `tasks._do_handle_owner_change` cria/altera `AssignedConversation`, `AssignmentLog`, `ConversationReassignment`, estado do ciclo e contadores | migrate-to-canonical | Migrar para reconciliação de owner e projeção/provenance única, preservando os controles de cada modo até o cutover. |
| Varredura periódica de NOVO | `auto_assign_service.sync_novo_stage_tickets` cria `NewConversation` e pode disparar assignment | migrate-to-canonical | Passar `entered_novo_at` comprovado pela admissão de ocorrência. Varredura não inventa identidade pelo horário da leitura. |
| Webhook de FECHADO → `task_handle_ticket_closed` | `auto_assign_service.handle_ticket_closed` interpreta a ocorrência; `ticket_close_service.reconcile_close_occurrence` aplica fechamento | canonical (evolve) | Persistir ocorrência `closed` antes da projeção; manter `ticket_close_service` como writer único. Remover do live o fallback de `timezone.now()` em `_close_occurrence`. |
| Snapshot fechado durante reconciliação de owner/capacity | `owner_reconciliation_service.reconcile_ticket` chama `_apply_ticket_closed` e depois grava occupancy | migrate-to-canonical | Sem `entered_closed_at`, persistir `provider_materialization_pending` sem gravar estado terminal ou liberar capacidade. Com horário comprovado, delegar ao mesmo writer de fechamento. |
| Projeção de fechamento | `ticket_close_service._materialize` cria `ClosedConversation`, remove `AssignedConversation`/`NewConversation`, fecha ciclo e ajusta contador legado | canonical | Permanece writer único de fechamento, somente com ocorrência comprovada. |
| Admissão de ciclo | `conversation_cycle_service.open_or_get_cycle` cria `SupportConversationCycle` com chave temporal | canonical | Chamada após prova de ocorrência; retirar admissão tardia dos caminhos de owner/capacity. |
| Ocupação atual do ticket | `capacity_service.ticket_transaction` cria/trava linha; `owner_reconciliation_service.reconcile_ticket` atualiza owner/estado/revisão; `durable_assignment_service` participa da reserva | canonical (evolve) | `owner_reconciliation_service` segue dono do estado atual. Estado terminal depende de fechamento comprovado; reservas continuam no protocolo durável. |
| Contador `Agent.current_simultaneous_chats` | `capacity_service.materialize` recalcula por occupancy/reserva em `enforce`; `queue_service`, `agent_sync_service`, `sat_service` e `tasks.task_reconcile_agent_counts` também escrevem | migrate-to-canonical | `capacity_service.materialize` é projeção autoritativa em `enforce`; remover writers legados depois do cutover. Pending de fechamento não libera capacidade. |
| Reserva e efeito de assignment | `durable_assignment_service` cria/finaliza `AssignmentAttempt`; `capacity_service.hold_capacity/conclude_reservation` grava `AgentCapacityReservation`; `HubSpotClient.assign_ticket_owner` faz PATCH | canonical | Preservar saga, readback, ordem de locks e I/O externo fora de locks. |
| Transferência administrativa | `admin_api` cria `ConversationReassignment`/`AssignmentLog` e chama PATCH HubSpot | migrate-to-canonical | Preservar intenção administrativa como prova; unificar projeção/provenance e manter reserva durável. |
| Provenance de owner externo | `owner_reconciliation_service._project_owner` e `tasks._do_handle_owner_change` rotulam mudança sem correlação como `manual`/`hubspot_manual` | remove | Correlacionar `AssignmentAttempt` ou intenção administrativa; sem prova do ator, persistir `unknown_external`. |
| Métricas de fila/agente | `tasks.task_aggregate_queue_metrics` e `tasks.task_aggregate_agent_metrics` agregam linhas ativas/fechadas e logs | migrate-to-canonical | Agregar por ciclo e provenance persistidos quando ciclo for a unidade; não inferir origem por logs. |
| Reparação de ciclos históricos | `legacy_cycle_backfill`, `backfill_conversation_cycles`, `reconcile_ticket_closures` e comandos de auditoria/reparo | historical-only | Manter dry-run bounded e drain separado; nenhum chamado a partir de tarefas live. |

## Leituras e efeitos no provider

| Capability | Chamada atual | Classificação | Contrato a estabelecer |
|---|---|---|---|
| Tickets read/write | `HubSpotClient.get_ticket_details`, `get_ticket`, `assign_ticket_owner`, chamados por matchmaker, reconciliações, assignment durável e admin | canonical adapter (evolve) | Fixar versão por capability; preservar readback antes de efeito e classificação tipada de falhas. |
| Busca de tickets | `HubSpotClient.search_tickets_in_novo_stage`, busca por owner, scans e comandos | migrate-to-canonical adapter | Centralizar URL, paginação, timeout e erros; resultado parcial nunca é completo. |
| Owners | `HubSpotClient.get_owner_details`; `get_team_members` lê só a primeira página de Owners | replace for membership | Owners só resolve ID de CRM owner. Teams 2026-09 fornece membership e Users 2026-09 fornece identidade/status. |
| Users/availability | `HubSpotClient.get_user_by_id`, listagens de owners/users; `sat_service` e jobs | canonical adapter (evolve) | Fixar versões e falhar em 401/403; autoridade de disponibilidade segue separada da presença na equipe. |
| Webhook ingress | ledger `WebhookEvent`, HMAC e dispatch em `apps/webhooks` | canonical transport | Preservar autenticação/dedup; handler delega ocorrência. Configuração desejada/publicada precisa de readback e detecção de drift. |
| Configuração remota | manifestos em `hubspot-app` | read-only até autorização separada | Documentar scopes mínimos e preflight; sem alterar publicação, scopes ou app na implementação local. |

## Gate de writer único antes de DB-01 / BE-01

Todos os fatos acima têm destino nomeado. Os writers duplicados de owner/assignment e contagem estão classificados para migração, sem serem tratados como canônicos. `lifecycle_occurrence_service` persiste evidência, mas não escreve occupancy/capacity nem executa efeitos HubSpot. `ticket_close_service` é o único projetor terminal; `conversation_cycle_service` é o único serviço de admissão de ciclos. A migration será aditiva e os writers históricos continuarão em lane separada.

## Âncoras no código

- Admissão: `apps/support/conversation_cycle_service.py:370`, `apps/support/matchmaker_service.py:347`, `apps/support/owner_reconciliation_service.py:215`.
- Fechamento e falha sem horário: `apps/support/ticket_close_service.py:144`, `apps/support/owner_reconciliation_service.py:253`.
- Writers de owner: `apps/support/owner_reconciliation_service.py:60`, `apps/support/tasks.py:562`.
- Capacidade/reservas: `apps/support/capacity_service.py:51`, `apps/support/durable_assignment_service.py:235`.
- Roster: `apps/integrations/hubspot/client.py:348`, `apps/support/auto_assign_service.py:553`.
- Manifestos: `hubspot-app/src/app/app-hsmeta.json`, `hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json`.

## Contrato externo conferido

- [Teams API 2026-09](https://developers.hubspot.com/docs/api-reference/latest/account/settings/teams/guide): `GET /settings/teams/2026-09/{teamId}/members`, com `limit` e `after`.
- [Users API 2026-09](https://developers.hubspot.com/docs/api-reference/latest/account/settings/user-provisioning/guide): `GET /settings/users/2026-09` e `GET /settings/users/2026-09/{userId}` para identidade.
