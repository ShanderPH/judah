# Auditoria arquitetural provisória — ARCH-02 / ARCH-03

## Fronteira dos adapters

Os novos `platform_contract.py`, `team_roster.py`, `ticket_provider.py` e `webhook_config.py` não importam serviços de `apps.support` nem escrevem no banco. O cliente HubSpot encaminha somente leitura, PATCH e roster. A classificação temporal e a projeção ficam em `lifecycle_occurrence_service.py` e nos writers de Support.

## Writers revisados

| Fato | Writer canônico observado | Estado |
|---|---|---|
| Entrada em ciclo | `conversation_cycle_service.open_or_get_cycle`, chamada por `lifecycle_occurrence_service` nos modos shadow/enforce | Há chamadas legadas diretas em `off` e histórico; o método de escrita é único. |
| Fechamento | `ticket_close_service.reconcile_close_occurrence` | Único projetor terminal; occurrence comprovada antes da projeção em shadow/enforce. |
| Ocorrência | `lifecycle_occurrence_service` | Único writer novo, migration aditiva. Owner sem ciclo fica pendente; ocorrência temporalmente anterior ao ciclo atual não é marcada como projetada. |
| Occupancy e contador | `owner_reconciliation_service.reconcile_ticket` + `capacity_service.materialize` em capacity enforce | `tasks.task_handle_owner_change` retorna antes do writer legado; `admin_api` usa a rota de capacidade; `queue_service` recusa incrementos/decrementos sem identidade. `agent_sync_service`, `sat_service` e `task_reconcile_agent_counts` usam refresh canônico e não corrigem o contador diretamente nesse modo. |
| Reserva/attempt | `durable_assignment_service` + `capacity_service` | Preservado; gate de capability antes do PATCH. Três saves da saga durável deixaram de incluir `current_simultaneous_chats` em `update_fields` quando a capacidade canônica está ativa. |
| Provenance | `assignment_provenance.classify_owner_effect` | Assignment logs novos usam a taxonomia canônica; a intenção administrativa preserva o motivo em `ConversationReassignment`. `AssignmentAttempt` ainda usa choices legadas próprias. |
| Mensagem humana | `webhooks.n8n_inbound.ingest_hubspot_message` | Resposta outbound hidratada guarda somente `actor_id` no ledger, sem copiar o texto para a prova de participação; bot configurado fica excluído. |
| Métricas | `tasks.task_aggregate_*` + `agent_message_evidence.attributed_agent_cycles` | Em `enforce`, ciclo conta para o último owner projetado. Owner anterior só entra se houver mensagem outbound dele no mesmo portal/ticket, dentro do ciclo e antes da transferência confirmada. Transferência reservada, sem horário, sem mapeamento `hubspot_user_id` ou sem mensagem fica fora. Linhas históricas sem ciclo conservam a contagem legada. |

**ARCH-03 não aprovado para rollout:** a separação dos writers do contador em `enforce` foi conferida por caminho de código e regressão de gravação concorrente. `off`/shadow e a rota administrativa sem capacidade canônica preservam writers legados de `AssignedConversation`, `AssignmentLog`, `ConversationReassignment` e contadores, sem escrever o contador canônico em shadow. Em `enforce`, `durable_assignment_service` finaliza attempts, `owner_reconciliation_service` projeta owner externo e `ticket_close_service` materializa o fechamento; essa divisão ainda exige amostra de convergência antes do rollout. `ConversationInstanceAttendant` ganhou `unknown_external`, mas `AssignmentAttempt` ainda não compartilha um enum canônico. A projeção por snapshot deixa `AssignedConversation.assigned_at` e `ConversationReassignment.reassigned_at` nulos quando o provider não prova o horário; os schemas de leitura agora aceitam `NULL`. O modo `enforce` exige `SUPPORT_CAPACITY_MODE=enforce`.

**Limite de evidência de mensagem:** só mensagens outbound hidratadas daqui em diante recebem `_agent_message_evidence`. O ledger histórico não foi reprocessado. Se um agente respondeu antes de o registro estar disponível, a métrica conservadora o omite; não se infere participação por log de atribuição. O parser aceita objeto legado ou lista em `threadAssociations`; múltiplos tickets distintos ficam sem atribuição. A HubSpot documenta a [lista de associações](https://developers.hubspot.com/changelog/march-2026-rollup) e o formato [`A-...` do ator humano](https://developers.hubspot.com/changelog/april-2026-rollup), mas o vínculo com `hubspot_user_id` e ticket ainda precisa de amostra sandbox nesta conta. Não promover a métrica sem essa verificação. A agregação histórica lê logs e transferências de todos os ciclos; medir custo no shadow.

**Migration `0035`:** forward, reverse em base vazia e forward novamente passaram em PostgreSQL 16 local. `assigned_at` e `reassigned_at` aceitam `NULL`; dois INSERTs de prova foram revertidos. O reverse só é seguro se nenhuma linha nula tiver sido persistida. Não é rollback operacional de produção.

O teste `test_reservation_does_not_overwrite_canonical_count` simula uma projeção concorrente entre a leitura e o save da reserva. A contagem projetada sobrevive ao save da saga. A auditoria deve continuar nos outros writers legados antes de declarar o gate fechado.

Não foi alterada a verificação HMAC. Journal e Conversations permanecem opcionais, sem promoção a fonte de lifecycle.
