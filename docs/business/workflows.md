# Fluxos de Trabalho

## Resumo

Descrição dos principais fluxos de negócio do JUDAH, do início ao fim, com regras e pontos de decisão.

## Contexto

Os fluxos conectam clientes finais, agentes de suporte, sistemas externos (HubSpot, Jira) e agentes de IA.

## 1. Fluxo de auto-atribuição de tickets

### Atores

- Cliente final (abre ticket no HubSpot)
- Sistema JUDAH (webhook, Matchmaker, SAT)
- Agente de suporte N1

### Passo a passo

1. Cliente abre ticket no HubSpot (chat, email, form).
2. HubSpot envia webhook `ticket.propertyChange` com `propertyName=hs_v2_date_entered_939275049`.
3. JUDAH valida assinatura HMAC e persiste `WebhookEvent`.
4. `hubspot_handler._handle_ticket_entered_novo` despacha `task_matchmaker_assign_single`.
5. A task:
   - Adquire lock Redis.
   - Busca detalhes do ticket no HubSpot.
   - Valida elegibilidade (pipeline correto, sem owner).
   - Cria registro em `NewConversation`.
   - Chama `matchmaker_assign_next`.
6. `matchmaker_assign_next`:
   - Seleciona agente via `queue_service.select_next_agent`.
   - Reconcilia carga via `sat_service.sat_reconcile_agent_load`.
   - Atualiza `hubspot_owner_id` no ticket.
   - Cria `AssignedConversation` e `AssignmentLog`.
   - Incrementa `current_simultaneous_chats` do agente.
7. Agente é notificado no HubSpot e atende o ticket.

### Decisões

- Se nenhum agente elegível: ticket fica em `NewConversation` com `queue_status=queued`.
- Se agente selecionado estiver cheio após reconciliação: tenta próximo agente.

### Arquivos relacionados

- [`apps/webhooks/handlers/hubspot_handler.py`](../../apps/webhooks/handlers/hubspot_handler.py)
- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/support/matchmaker_service.py`](../../apps/support/matchmaker_service.py)
- [`apps/support/queue_service.py`](../../apps/support/queue_service.py)

## 2. Fluxo de fechamento de ticket

### Passo a passo

1. Ticket é movido para FECHADO (`939275052`) no HubSpot.
2. HubSpot envia webhook com `hs_v2_date_entered_939275052`.
3. JUDAH persiste evento e despacha `task_handle_ticket_closed`.
4. A task adquire lock Redis.
5. Se houver `AssignedConversation`:
   - Calcula handle time e resolution time.
   - Decrementa contador do agente atribuído.
   - Cria `ClosedConversation`.
   - Remove `AssignedConversation`.
6. Se não houver atribuição: cria `ClosedConversation` mínimo.

### Decisões

- O decremento é do agente atribuído, não de quem fechou.
- Fechamento duplicado é ignorado via lock.

### Arquivos relacionados

- [`apps/support/auto_assign_service.py`](../../apps/support/auto_assign_service.py)
- [`apps/support/tasks.py`](../../apps/support/tasks.py)

## 3. Fluxo de chat com Salomão

### Passo a passo

1. Usuário autenticado envia mensagem para `POST /api/v1/ai/salomao/chat`.
2. Endpoint instancia `SalomaoSupervisorAgent` com `session_id=user-{pk}`.
3. `run_pipeline_async` chama `run_pipeline`.
4. `run_pipeline`:
   - Verifica circuit breaker (15k tokens).
   - Injeta regra de greeting (primeira mensagem).
   - Executa `Team.run(message)`.
5. Team coordena:
   - `HeimdallTriageAgent` retorna `TriageResult`.
   - Baseado em `rota`, aciona `KnowledgeRagAgent` ou `HelpdeskActionAgent`.
6. Resposta é formatada como `SalomaoResponse`.
7. `TokenTrackingLog` registra tokens e custo.

### Decisões

- Se circuit breaker ativado: resposta de handoff imediato.
- Se RAG não encontrar resposta: sinaliza `<REQUIRES_ESCALATION>` e Action Agent atualiza ticket.
- Se `prioridade == CRITICA`: handoff humano.

### Arquivos relacionados

- [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py)
- [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py)
- [`apps/ai_agents/agents/triage.py`](../../apps/ai_agents/agents/triage.py)
- [`apps/ai_agents/agents/rag.py`](../../apps/ai_agents/agents/rag.py)
- [`apps/ai_agents/agents/action.py`](../../apps/ai_agents/agents/action.py)

## 4. Fluxo de webhook HubSpot → Supervisor de IA

> **Nota:** `apps/ai_agents/api/webhooks.py` define `/hubspot/ticket-change`, mas esse router **não está montado** em `core/urls.py`. O fluxo real de IA passa pelo webhook canônico `/api/v1/webhooks/hubspot/` quando `AI_ROUTING_ENABLED=true`.

### Passo a passo

1. HubSpot envia `ticket-change` para `/api/v1/webhooks/hubspot/`.
2. O handler canônico valida HMAC v1/v3 e persiste `WebhookEvent`.
3. Quando o ticket entra em `HUBSPOT_N1_NEW_STAGE_ID`, ou recebe uma nova mensagem em `hs_last_message_from_visitor`, o handler dispara `run_supervisor_pipeline_task.delay(ticket_id, is_off_hours, True)`.
4. A task adquire lock Redis.
5. `_run_supervisor_pipeline`:
   - Hidrata contexto do ticket via HubSpot API.
   - Confirma que o ticket pertence a `HUBSPOT_AI_TRIAGE_PIPELINE_ID`.
   - Move o ticket para `HUBSPOT_AI_TRIAGE_STAGE_ID` durante o atendimento.
   - Monta mensagem com assunto, canal e histórico.
   - Executa Supervisor.
   - Envia a resposta para a thread do cliente.
   - Move para `HUBSPOT_AI_WAITING_STAGE_ID` ou `HUBSPOT_HUMAN_ESCALATION_STAGE_ID`.
   - Registra `TokenTrackingLog`.

### Decisões

- Fora do horário comercial: o pipeline ainda roda, mas a mensagem inclui `is_off_hours=True`; Action Agent deve usar stage off-hours.
- Se assinatura inválida: retorna 401 (canônico) ou 500 (comportamento depende do router). Nunca aceita em produção sem `HUBSPOT_APP_SECRET`.

### Arquivos relacionados

- [`apps/webhooks/api.py`](../../apps/webhooks/api.py)
- [`apps/webhooks/handlers/hubspot_handler.py`](../../apps/webhooks/handlers/hubspot_handler.py)
- [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py) *(router definido, mas não montado)*
- [`apps/ai_agents/tasks.py`](../../apps/ai_agents/tasks.py)
- [`apps/ai_agents/services/hubspot.py`](../../apps/ai_agents/services/hubspot.py)

## 5. Fluxo de SAT (Smart Agent Tracking)

### Passo a passo

1. Celery Beat dispara `task_sat_heartbeat` a cada 20s.
2. Task verifica se está em horário comercial.
3. Busca availability de todos os owners no HubSpot (`get_all_owners_availability`).
4. Para cada agente ativo:
   - Compara status local com remoto.
   - Acumula tempo no status anterior.
   - Atualiza `Agent.status_enum`.
   - Cria `AgentStatusHistory`.
5. Se algum agente ficou online, dispara `task_matchmaker_drain_queue`.
6. À meia-noite, `task_sat_reset_daily_counters` salva snapshot em `AgentDailyTimeLog`.

### Decisões

- Fora do horário: nenhuma chamada HubSpot.
- Agentes não encontrados na API HubSpot são logados como aviso.

### Arquivos relacionados

- [`apps/support/sat_service.py`](../../apps/support/sat_service.py)
- [`apps/support/tasks.py`](../../apps/support/tasks.py)

## 6. Fluxo de analytics diário

### Passo a passo

1. Às 00:05, `task_aggregate_queue_metrics` agrega o dia anterior.
2. Calcula:
   - Total de entradas na fila.
   - Total atribuídos.
   - Total fechados.
   - Tempos de espera (avg, min, max, p50, p95).
   - Tempo médio de handle.
   - Atribuições por agente.
3. Salva em `QueuePerformanceMetrics`.
4. Às 00:10, `task_aggregate_agent_metrics` agrega métricas por agente.
5. Salva em `AgentMetrics`.

### Arquivos relacionados

- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/analytics/tasks.py`](../../apps/analytics/tasks.py)
- [`apps/analytics/services.py`](../../apps/analytics/services.py)

## Pontos de atenção

- O fluxo de auto-atribuição e o fluxo de IA competem pelo mesmo ticket? Inferência baseada no código: ambos reagem ao webhook, mas `AI_ROUTING_ENABLED` desabilita o router de IA, enquanto o webhook canônico sempre dispara Matchmaker. **TODO: confirmar** se há sobreposição quando IA está habilitada.
- O fechamento via `hs_pipeline_stage` e `hs_v2_date_entered_939275052` pode chegar quase simultaneamente; o lock Redis mitiga, mas ainda há janela de corrida.

## Recomendações

- Desenhar um diagrama de sequência formal para cada fluxo crítico.
- Automatizar testes de integração para webhooks com payloads reais.
- Documentar decisões de fallback quando APIs externas falham.
