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

O endpoint `/api/v1/webhooks/hubspot/` é a entrada canônica e o backend é a
autoridade do workflow. O router alternativo em `apps/ai_agents/api/webhooks.py`
não é montado; ele concentra o worker reutilizado pelas tasks Celery.

### Passo a passo

1. HubSpot envia o evento para `/api/v1/webhooks/hubspot/`.
2. O endpoint valida HMAC v1/v3, incluindo a janela antirreplay de cinco
   minutos da assinatura v3, e persiste um `WebhookEvent` idempotente.
3. `process_webhook_event_task` normaliza o evento e o
   `RoutingPolicyEngine` escolhe exatamente uma rota: `IGNORE`, `CLOSE`,
   `AUTO_ASSIGNMENT`, `AI_TRIAGE` ou `HUMAN_HANDOFF`.
4. Em `AI_TRIAGE`, o worker hidrata `ConversationContext`, sanitiza o
   conteúdo e bloqueia tentativas explícitas de prompt injection antes do LLM.
5. Heimdall retorna `TriageDecision` com rota, prioridade, sentimento, dados
   faltantes, confiança, evidências e versão da política.
6. Dados faltantes produzem uma pergunta objetiva e o estado
   `WAITING_FOR_CUSTOMER`; risco, baixa confiança ou canal incompatível
   produzem handoff humano.
7. Com contexto suficiente, o serviço especializado é executado e o
   Supervisor retorna apenas `waiting_customer`, `candidate_resolved`,
   `escalate_human` ou `failed`.
8. Respostas e handoffs são aplicados pela camada de execução com permissão
   por estado, chave de idempotência, `AgentRun` e `ToolCallAuditLog`.
9. Uma resolução candidata permanece em `WAITING_FOR_CUSTOMER`; somente uma
   confirmação determinística do cliente leva a `RESOLVED_BY_AI` e `CLOSED`.
10. Handoffs criam `HandoffPackage`, entram no Matchmaker e avançam para os
    estados humanos. Falhas transitórias usam retry limitado, watchdog e
    fallback seguro para atendimento humano.

### Decisões

- Eventos duplicados não repetem dispatch nem efeitos externos.
- Fora do horário comercial, `ConversationContext.is_off_hours` informa a
  política e o handoff continua disponível.
- Sem `HUBSPOT_APP_SECRET` fora de DEBUG, o endpoint falha fechado.

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

- O fechamento via `hs_pipeline_stage` e `hs_v2_date_entered_939275052` pode chegar quase simultaneamente; o lock Redis mitiga, mas ainda há janela de corrida.
- A proteção contra prompt injection é determinística e conservadora; deve
  ser complementada por evals contínuos e monitoramento de falsos positivos.

## Recomendações

- Desenhar um diagrama de sequência formal para cada fluxo crítico.
- Automatizar testes de integração para webhooks com payloads reais.
- Documentar decisões de fallback quando APIs externas falham.
