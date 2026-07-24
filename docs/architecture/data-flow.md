# Fluxo de Dados

## Resumo

Este documento descreve os principais fluxos de dados do JUDAH: recebimento de webhook do HubSpot, auto-atribuição de tickets, chat com o agente Salomão e agregação de analytics.

## Contexto

Os fluxos são orquestrados por uma combinação de endpoints síncronos do Django Ninja e tarefas assíncronas do Celery. O Redis atua como broker do Celery, cache e armazenamento de sessão dos agentes de IA.

## 1. Webhook HubSpot → Auto-atribuição

```text
HubSpot
  │ ticket.propertyChange (hs_v2_date_entered_939275049)
  ▼
/api/v1/webhooks/hubspot/  [apps/webhooks/api.py]
  │ 1. Verifica HMAC v1/v3
  │ 2. Persiste WebhookEvent
  ▼
apps/webhooks/handlers/hubspot_handler.py
  │ Identifica evento de ticket.propertyChange NOVO
  │ Registra lifecycle: ConversationInstance + ConversationEvent + QUEUE_PENDING
  ▼
task_matchmaker_assign_single  [apps/support/tasks.py]
  │ 1. Deduplica via Redis lock
  │ 2. Enqueue em NewConversation
  ▼
matchmaker_assign_next  [apps/support/matchmaker_service.py]
  │ 1. Seleciona agente (queue_service)
  │ 2. Reconcilia carga (sat_service)
  │ 3. Atualiza HubSpot owner_id
  ▼
AssignedConversation + AssignmentLog
```

### Regras de negócio

- Apenas tickets no pipeline `636459134` e sem owner são elegíveis.
- A seleção de agente segue 4 regras: online, evitar repetição imediata, maior tempo desde última atribuição, menor carga atual.
- A fila é FIFO baseada em `entered_queue_at`.

### Arquivos relacionados

- [`apps/webhooks/api.py`](../../apps/webhooks/api.py)
- [`apps/webhooks/handlers/hubspot_handler.py`](../../apps/webhooks/handlers/hubspot_handler.py)
- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/support/matchmaker_service.py`](../../apps/support/matchmaker_service.py)
- [`apps/support/queue_service.py`](../../apps/support/queue_service.py)

## 2. Fechamento de ticket

```text
HubSpot
  │ ticket.propertyChange (hs_v2_date_entered_939275052)
  ▼
api/webhooks/hubspot/
  ▼
hubspot_handler._handle_ticket_entered_closed
  ▼
task_handle_ticket_closed
  │ 1. Redis lock por ticket
  │ 2. Calcula handle time
  │ 3. Decrementa contador do agente
  ▼
ClosedConversation
```

### Regras de negócio

- O decremento do contador de chats é sempre do agente que foi atribuído, não de quem fechou.
- Fechamentos duplicados são idempotentes graças ao Redis lock.

### Arquivos relacionados

- [`apps/support/auto_assign_service.py`](../../apps/support/auto_assign_service.py)

## 3. Chat com Salomão (quando AI_ROUTING_ENABLED=true)

### 3.1 Chat autenticado

```text
Usuário autenticado
  │
  ▼
POST /api/v1/ai/salomao/chat  [apps/ai_agents/api/routers.py]
  │
  ▼
SalomaoSupervisorAgent.run_pipeline_async
  │ 1. Circuit breaker (15k tokens acumulados)
  │ 2. Injeção de greeting na primeira mensagem
  │ 3. Team.run(message)
  ▼
HeimdallTriageAgent ──► TriageResult
  │
  ├── rota = DUVIDAS_PLATAFORMA / ATENDIMENTO_IA → KnowledgeRagAgent
  ├── rota = SUPORTE_TECNICO_N1 / FINANCEIRO / BOLETO / EVENTOS → HelpdeskActionAgent
  └── rota = ESCALAR_IMEDIATAMENTE → handoff humano
  ▼
SalomaoResponse + TokenTrackingLog
```

### 3.2 Webhook HubSpot → Supervisor

```text
HubSpot event
  │
  ▼
/api/v1/webhooks/hubspot/  [apps/webhooks/api.py]
  │ 1. HMAC v1/v3 + replay window
  │ 2. WebhookEvent + deduplication_key
  ▼
process_webhook_event_task
  │
  ▼
EventNormalizer → RoutingPolicyEngine
  │
  ├── IGNORE / CLOSE / AUTO_ASSIGNMENT → handler determinístico
  ├── HUMAN_HANDOFF → HandoffPackage + Matchmaker
  └── AI_TRIAGE → worker do Supervisor
  ▼
ConversationContext + content safety
  │
  ▼
Heimdall → TriageDecision
  │
  ├── dados faltantes → pergunta focada → WAITING_FOR_CUSTOMER
  ├── risco/baixa confiança → HUMAN_HANDOFF_REQUESTED
  └── serviço especializado → SupervisorDecision
  ▼
execution.apply_supervisor_result
  │ 1. AgentRun
  │ 2. ToolCallAuditLog
  │ 3. permissão por estado + idempotência
  ▼
WAITING_FOR_CUSTOMER / QUEUE_PENDING / FAILED_RETRYABLE
```

Uma resposta considerada candidata à resolução não fecha a conversa. O estado
permanece em `WAITING_FOR_CUSTOMER` até confirmação explícita e determinística
do cliente. Só então o lifecycle avança por `RESOLVED_BY_AI` até `CLOSED`.

### 3.3 Retry, watchdog e handoff

- Tasks de webhook e IA usam até três retries com backoff exponencial.
- O watchdog periódico detecta instâncias presas e marca
  `FAILED_RETRYABLE`.
- O dispatcher periódico reenvia instâncias elegíveis; ao esgotar o orçamento,
  encaminha tickets ao atendimento humano ou usa `FAILED_TERMINAL` quando não
  há identificador operacional para handoff.
- O Matchmaker atualiza o lifecycle para `HUMAN_ASSIGNED` após atribuição.

O Salomão v1 continua disponível como membro interno `SalomaoChat`, quando
configurado, mas não controla transições nem efeitos externos.

### Arquivos relacionados

- [`apps/ai_agents/api/routers.py`](../../apps/ai_agents/api/routers.py)
- [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py)
- [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py)
- [`apps/ai_agents/tasks.py`](../../apps/ai_agents/tasks.py)

## 4. SAT (Smart Agent Tracking)

```text
Celery Beat (a cada 20s)
  │
  ▼
task_sat_heartbeat
  │ 1. Sai se fora do horário comercial
  │ 2. Busca disponibilidade de todos os owners no HubSpot
  │ 3. Atualiza Agent.status_enum
  ▼
Se algum agente ficou online:
  ▼
task_matchmaker_drain_queue
```

### Regras de negócio

- Fora do horário comercial, o heartbeat não faz chamadas à API do HubSpot.
- Transições de status acumulam tempo em `Agent.online_time_seconds_today` / `away_time_seconds_today`.
- A meia-noite, `task_sat_reset_daily_counters` salva o snapshot em `AgentDailyTimeLog`.

### Arquivos relacionados

- [`apps/support/sat_service.py`](../../apps/support/sat_service.py)
- [`apps/support/agent_sync_service.py`](../../apps/support/agent_sync_service.py)

## 5. Analytics

```text
Celery Beat (diário 00:05)
  │
  ▼
task_aggregate_queue_metrics
  │ Agrega NewConversation, AssignedConversation, ClosedConversation
  ▼
QueuePerformanceMetrics

Celery Beat (diário 00:10)
  │
  ▼
task_aggregate_agent_metrics
  │ Agrega ClosedConversation, AssignmentLog, AgentDailyTimeLog
  ▼
AgentMetrics
```

### Arquivos relacionados

- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/analytics/tasks.py`](../../apps/analytics/tasks.py)
- [`apps/analytics/services.py`](../../apps/analytics/services.py)

## Pontos de atenção

- O endpoint `/api/v1/ai/webhooks/hubspot/ticket-change` usa `run_supervisor_pipeline_task.delay`, mas a task interna executa `asyncio.run(_run_supervisor_pipeline(...))`. O mix de sync Celery + async pode gerar problemas de event loop em workers com concorrência alta.
- Locks Redis são uma proteção adicional; a idempotência principal do evento
  bruto e do lifecycle também é persistida no banco.
- O webhook de ticket fechado pode ser disparado por `hs_pipeline_stage` e por `hs_v2_date_entered_939275052`; o código evita duplicidade via lock, mas o risco de corrida existe.

## Recomendações

- Monitorar latência do `task_matchmaker_assign_single` e da hidratação do ticket.
- Adicionar tracing distribuído (Sentry já captura transações, mas o propagation do `request_id` para Celery poderia ser formalizado).
- Monitorar a dead-letter queue de webhooks e os handoffs causados por retry
  esgotado.
