# Auto-Assignment System — Fila de Atribuição Automática

## Visão Geral

Sistema completo de atribuição automática de tickets HubSpot para agentes de suporte N1,
com fila de atendimento ranqueada, metrificação de tempos de espera, rastreamento de
encerramento de atendimentos, e sincronização inteligente de disponibilidade de agentes (SAT).

---

## Arquitetura

### Fluxo Principal (Matchmaker Async)

```
HubSpot Webhook (ticket.propertyChange → hs_v2_date_entered_939275049)
    │
    ▼
hubspot_handler._handle_ticket_entered_novo()
    │
    ▼ (Celery task: task_matchmaker_assign_single)
    │
    ▼
matchmaker_service.enqueue_new_ticket()
    │   1. Busca detalhes do ticket na HubSpot API
    │   2. Valida pipeline (636459134) e ausência de owner
    │   3. Cria registro em new_conversations (idempotente)
    │
    ▼
matchmaker_service.matchmaker_assign_next()
    │   • select_for_update(skip_locked=True) — previne race conditions
    │   • Redis lock por ticket — deduplicação entre workers
    │
    ▼
queue_service.select_next_agent()
    │   Aplica regras de prioridade 1-4 (ver abaixo)
    │
    ▼
sat_service.sat_reconcile_agent_load()
    │   Reconcilia carga real do agente com HubSpot
    │
    ▼
HubSpotClient.assign_ticket_owner()
    │   Atualiza hubspot_owner_id via API
    │
    ▼
DB Transaction (atômica):
    • new_conversations → DELETE (remove da fila)
    • assigned_conversations → UPSERT
    • assignment_logs → INSERT
    • agents → UPDATE (current_simultaneous_chats++, last_assignment_at)
```

### SAT (Smart Agent Tracking)

```
Celery Beat (a cada 20s)
    │
    ▼
task_sat_heartbeat()
    │
    ▼
sat_service.sat_heartbeat()
    │   1. Busca agentes ativos do time N1 no HubSpot
    │   2. Atualiza status_enum (ONLINE/AWAY/OFFLINE/BUSY)
    │   3. Reconcilia current_simultaneous_chats com tickets abertos
    │   4. Acumula tempo de status (online_time_seconds_today, etc.)
    │
    ▼ (se agente ficou ONLINE)
    │
task_matchmaker_drain_queue()
    │   Processa todos os tickets pendentes FIFO
```

### Sincronização NOVO Stage (Startup/Diário)

```
task_sync_novo_stage_tickets() — executa no startup do worker + diariamente
    │
    ▼
auto_assign_service.sync_novo_stage_tickets()
    │   1. Busca todos os tickets no estágio NOVO (939275049)
    │   2. Skip: tickets com owner_id (já atribuídos manualmente)
    │   3. Skip: tickets já existentes em new_conversations
    │   4. Skip: tickets já existentes em assigned_conversations
    │   5. Cria registros em new_conversations para tickets novos
    │
    ▼
assign_pending_tickets()
    │   Tenta atribuir todos os tickets pendentes
```

---

## Regras de Prioridade da Fila (4 Regras)

### Critérios de Elegibilidade (pre-filtro)

Antes de aplicar as regras de prioridade, um agente deve satisfazer:

| Critério | Descrição |
|----------|-----------|
| `status_enum = ONLINE` | Apenas agentes online (exclui AWAY, OFFLINE, BUSY) |
| `auto_assign_enabled = True` | Participação na atribuição automática habilitada |
| `is_active != False` | Agente ativo no sistema |
| `current_simultaneous_chats < max_simultaneous_chats` | Abaixo do limite de capacidade |

### Algoritmo de Seleção

| # | Regra | Descrição |
|---|-------|-----------|
| 1 | **Status ONLINE** | Somente agentes online são elegíveis |
| 2 | **No Consecutive** | Nunca atribuir dois consecutivos ao mesmo agente (exceto se único online) |
| 3 | **Last Assignment** | Preferência para agente com maior tempo desde última atribuição (`NULL` = máxima prioridade) |
| 4 | **Load Balancing** | Entre empatados, preferência para o com menos chats simultâneos |

### Ordenação Final

```python
_sort_key = (last_assignment_at ASC, current_simultaneous_chats ASC)
# NULL last_assignment_at → tratado como epoch 2000-01-01 (máxima prioridade)
```

---

## Tabelas de Banco de Dados

### `new_conversations`
Tickets que entraram no estágio NOVO e aguardam atribuição.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `hubspot_ticket_id` | TEXT UNIQUE | ID do ticket no HubSpot |
| `pipeline_id` | TEXT | Pipeline (padrão: 636459134) |
| `contact_name` | TEXT | Nome do contato |
| `contact_email` | TEXT | Email do contato |
| `priority` | TEXT | Prioridade do ticket |
| `subject` | TEXT | Assunto do ticket |
| `entered_queue_at` | TIMESTAMPTZ | Valor de `hs_v2_date_entered_939275049` (ordenação FIFO) |
| `queue_status` | VARCHAR(20) | `pending` (novo) ou `queued` (aguardando agente) |
| `assignment_attempts` | INT | Contador de tentativas de atribuição |
| `last_assignment_attempt_at` | TIMESTAMPTZ | Última tentativa de atribuição |
| `created_at` | TIMESTAMPTZ | Criação do registro |
| `updated_at` | TIMESTAMPTZ | Última atualização |

### `assigned_conversations`
Tickets atribuídos pelo sistema automático ou manualmente.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `hubspot_ticket_id` | TEXT UNIQUE | ID do ticket |
| `agent_id` | UUID FK | Agente atribuído (local DB) |
| `hubspot_owner_id` | BIGINT | ID do owner no HubSpot |
| `agent_name` | TEXT | Nome do agente (cache) |
| `pipeline_id` | TEXT | Pipeline do ticket |
| `contact_name` | TEXT | Nome do contato |
| `contact_email` | TEXT | Email do contato |
| `priority` | TEXT | Prioridade |
| `subject` | TEXT | Assunto |
| `entered_queue_at` | TIMESTAMPTZ | Quando entrou na fila |
| `assigned_at` | TIMESTAMPTZ | Quando foi atribuído |
| `queue_wait_seconds` | NUMERIC | Tempo de espera na fila (segundos) |
| `closed_at` | TIMESTAMPTZ | Quando o atendimento foi encerrado |
| `total_handle_time_minutes` | NUMERIC | Tempo total de atendimento |
| `assignment_count` | INT | Número de atribuições (para reatribuições) |
| `created_at` | TIMESTAMPTZ | Criação |
| `updated_at` | TIMESTAMPTZ | Última atualização |

### `closed_conversations`
Histórico de tickets encerrados (arquivamento).

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `hubspot_ticket_id` | TEXT | ID do ticket |
| `agent_id` | UUID FK | Agente que atendeu |
| `hubspot_owner_id` | BIGINT | ID do owner no HubSpot |
| `entered_queue_at` | TIMESTAMPTZ | Entrada na fila |
| `assigned_at` | TIMESTAMPTZ | Atribuição |
| `closed_at` | TIMESTAMPTZ | Encerramento |
| `queue_wait_seconds` | NUMERIC | Espera na fila |
| `total_handle_time_minutes` | NUMERIC | Tempo total de atendimento |
| `created_at` | TIMESTAMPTZ | Criação |

### `agents` (tabela principal de agentes)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `hubspot_owner_id` | BIGINT UNIQUE | ID do owner no HubSpot |
| `name` | TEXT | Nome do agente |
| `agent_email` | TEXT | Email do agente |
| `status_enum` | VARCHAR(20) | `online`, `away`, `offline`, `busy` |
| `auto_assign_enabled` | BOOLEAN | Participa da atribuição automática |
| `is_active` | BOOLEAN | Agente ativo no sistema |
| `current_simultaneous_chats` | INT | Chats abertos atualmente |
| `max_simultaneous_chats` | INT | Limite de chats (default: 5) |
| `last_assignment_at` | TIMESTAMPTZ | Última atribuição recebida |
| `total_assignments` | INT | Total de atribuições acumulado |
| `last_status_change_at` | TIMESTAMPTZ | Última mudança de status |
| `online_time_seconds_today` | BIGINT | Tempo online acumulado hoje |
| `away_time_seconds_today` | BIGINT | Tempo away acumulado hoje |
| `sat_last_sync_at` | TIMESTAMPTZ | Último sync SAT |
| `sat_last_count_sync_at` | TIMESTAMPTZ | Última reconciliação de contagem |
| `created_at` | TIMESTAMPTZ | Criação |
| `updated_at` | TIMESTAMPTZ | Última atualização |

### `queue_performance_metrics`
Métricas diárias agregadas da fila.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `metric_date` | DATE UNIQUE | Data da métrica |
| `total_entered_queue` | INT | Tickets que entraram na fila |
| `total_assigned` | INT | Atribuições realizadas |
| `total_closed` | INT | Atendimentos encerrados |
| `avg_queue_wait_seconds` | NUMERIC | Tempo médio de espera (segundos) |
| `min_queue_wait_seconds` | NUMERIC | Mínimo de espera |
| `max_queue_wait_seconds` | NUMERIC | Máximo de espera |
| `p50_queue_wait_seconds` | NUMERIC | Mediana do tempo de espera |
| `p95_queue_wait_seconds` | NUMERIC | Percentil 95 do tempo de espera |
| `avg_handle_time_minutes` | NUMERIC | Tempo médio de atendimento |
| `assignments_by_agent` | JSONB | Atribuições por agente `{owner_id: count}` |
| `created_at` | TIMESTAMPTZ | Criação |
| `updated_at` | TIMESTAMPTZ | Última atualização |

### `assignment_logs` (auditoria)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `ticket_id` | TEXT | ID do ticket no HubSpot |
| `agent_id` | UUID FK | Agente (se conhecido) |
| `agent_name` | TEXT | Nome do agente |
| `hubspot_owner_id` | BIGINT | ID do owner no HubSpot |
| `assignment_type` | VARCHAR(20) | `automatic`, `manual`, `reassignment` |
| `pipeline_id` | TEXT | Pipeline |
| `entered_queue_at` | TIMESTAMPTZ | Entrada na fila |
| `assigned_at` | TIMESTAMPTZ | Atribuição (timestamp) |
| `queue_wait_seconds` | NUMERIC | Tempo de espera na fila |

### `conversation_reassignments`
Histórico de remanejamentos entre agentes.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `hubspot_ticket_id` | TEXT | ID do ticket |
| `from_agent_id` | UUID FK | Agente anterior |
| `from_hubspot_owner_id` | BIGINT | Owner ID anterior |
| `from_agent_name` | TEXT | Nome agente anterior |
| `to_agent_id` | UUID FK | Novo agente |
| `to_hubspot_owner_id` | BIGINT | Novo owner ID |
| `to_agent_name` | TEXT | Nome novo agente |
| `reassigned_at` | TIMESTAMPTZ | Timestamp da remanejo |
| `time_with_previous_agent_seconds` | NUMERIC | Tempo com agente anterior |
| `reassignment_source` | VARCHAR(50) | Fonte do remanejo |

### `agent_status_history`
Histórico de mudanças de status dos agentes.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `agent_id` | UUID FK | Agente |
| `old_status` | VARCHAR(20) | Status anterior |
| `new_status` | VARCHAR(20) | Novo status |
| `changed_at` | TIMESTAMPTZ | Timestamp da mudança |
| `sync_source` | VARCHAR(50) | Fonte (webhook, sat_heartbeat, etc.) |

### `agent_daily_time_logs`
Logs diários de tempo por status.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | UUID PK | ID interno |
| `agent_id` | UUID FK | Agente |
| `log_date` | DATE | Data do log |
| `online_time_seconds` | BIGINT | Tempo online em segundos |
| `away_time_seconds` | BIGINT | Tempo away em segundos |
| `created_at` | TIMESTAMPTZ | Criação |
| `updated_at` | TIMESTAMPTZ | Última atualização |

### `agent_metrics`
Métricas agregadas por agente.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `agent_id` | BIGINT PK | HubSpot owner ID |
| `total_chats` | INT | Total de chats |
| `chats_closed` | INT | Chats encerrados |
| `average_ticket_time_min` | NUMERIC | Tempo médio de atendimento |
| `average_response_time_min` | NUMERIC | Tempo médio de resposta |
| `average_online_time` | NUMERIC | Tempo médio online |
| `average_away_time` | NUMERIC | Tempo médio away |
| `last_time_updated` | TIMESTAMPTZ | Última atualização |

---

## Triggers do Webhook HubSpot

| Evento | Propriedade | Handler Celery | Descrição |
|--------|-------------|----------------|-----------|
| `ticket.propertyChange` | `hs_v2_date_entered_939275049` | `task_matchmaker_assign_single` | Ticket entrou em NOVO → enfileira e tenta atribuir |
| `ticket.propertyChange` | `hs_v2_date_entered_939275052` | `task_handle_ticket_closed` | Ticket entrou em FECHADO → registra encerramento |
| `ticket.propertyChange` | `hs_pipeline_stage` | — | Atualiza estágio local (legado) |
| `ticket.propertyChange` | `hubspot_owner_id` | `task_handle_owner_change` | Mudança de owner → ajusta contadores e loga remanejo |
| `contact.propertyChange` | `hs_chat_transfer_availability` | `task_handle_availability_change` | Agente mudou disponibilidade → atualiza status_enum |

---

## Validações Antes da Atribuição

1. **Pipeline correto**: `hs_pipeline` deve ser `636459134`
2. **Sem owner**: `hubspot_owner_id` deve estar vazio/nulo

Se qualquer validação falhar, o ticket não é processado pela fila.

---

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/v1/support/queue/status/` | Snapshot do estado atual da fila |
| GET | `/api/v1/support/queue/pending/` | Tickets aguardando atribuição |
| GET | `/api/v1/support/queue/assigned/` | Conversas atribuídas (filtros: agent_owner_id, closed) |
| GET | `/api/v1/support/queue/metrics/` | Métricas de desempenho da fila (parâmetro: days) |

---

## Tarefas Celery

### SAT (Smart Agent Tracking)

| Task | Schedule | Descrição |
|------|----------|-----------|
| `support.task_sat_heartbeat` | A cada 20s | Sync de disponibilidade dos agentes do HubSpot |
| `support.task_sat_reset_daily_counters` | 00:01 AM (America/Sao_Paulo) | Reset dos contadores diários de tempo |

### Matchmaker (Async Assignment)

| Task | Schedule | Descrição |
|------|----------|-----------|
| `support.task_matchmaker_assign_single` | On-demand (webhook) | Enfileira ticket e tenta atribuir imediatamente |
| `support.task_matchmaker_drain_queue` | On-demand / 60s | Processa todos os tickets pendentes FIFO |

### Lifecycle (Webhooks)

| Task | Schedule | Descrição |
|------|----------|-----------|
| `support.task_handle_ticket_closed` | On-demand | Registra encerramento e calcula handle time |
| `support.task_handle_owner_change` | On-demand | Processa remanejamento entre agentes |
| `support.task_handle_availability_change` | On-demand | Atualiza status do agente e dispara drain se online |

### Aggregation & Sync

| Task | Schedule | Descrição |
|------|----------|-----------|
| `support.task_sync_hubspot_team_members` | Diário 06:00 | Sincroniza membros do time N1 com tabela agents |
| `support.task_sync_novo_stage_tickets` | Startup + Diário | Backfill de tickets em NOVO stage |
| `support.task_aggregate_queue_metrics` | Diário 00:05 | Agrega métricas da fila do dia anterior |
| `support.task_aggregate_agent_metrics` | Diário 00:10 | Agrega métricas por agente |
| `support.task_reconcile_agent_counts` | Horário (business hours) | Reconcilia contagem de chats local vs HubSpot |
| `support.task_requeue_stale_assignments` | Periódico | Re-enfileira tickets com agentes inativos (>30min) |

---

## Gestão de Agentes

- Agentes são mantidos na tabela `agents` no Supabase.
- Para **adicionar** um agente: inserir na tabela `agents` com `hubspot_owner_id` correto.
- Para **remover** da fila: setar `is_active = false` ou `auto_assign_enabled = false`.
- A sincronização automática diária (`task_sync_hubspot_team_members`) cria novos agentes
  do time HubSpot automaticamente. O ID do time é configurável via `HUBSPOT_N1_TEAM_ID`.

---

## Variáveis de Ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `HUBSPOT_ACCESS_TOKEN` | — | Token de acesso à API HubSpot (obrigatório) |
| `HUBSPOT_APP_SECRET` | — | Secret para validação de assinatura do webhook |
| `HUBSPOT_N1_TEAM_ID` | `8` | ID do time N1 no HubSpot para sync de agentes |

---

## Arquivos Criados / Modificados

### Core Services

```
apps/support/
├── models.py                    ← Modelos: Agent, NewConversation, AssignedConversation,
│                                    ClosedConversation, QueuePerformanceMetrics,
│                                    AssignmentLog, ConversationReassignment,
│                                    AgentStatusHistory, AgentDailyTimeLog, AgentMetrics
├── migrations/
│   └── 0002_auto_assignment_tables.py
│   └── 0003_agent_enhancements.py
│   └── 0004_assignment_tracking.py
│
├── queue_service.py             ← Algoritmo de seleção de agentes (4 regras)
├── auto_assign_service.py       ← Orquestração da atribuição automática
├── matchmaker_service.py        ← Async assignment com locks e reconciliação
├── sat_service.py               ← Smart Agent Tracking (heartbeat, sync)
├── agent_sync_service.py        ← Sincronização de agentes com HubSpot
├── tasks.py                     ← Todas as tarefas Celery
├── schemas.py                   ← Schemas Pydantic da fila
├── api.py                       ← Endpoints REST da fila
└── hubspot_event_mapping.py     ← Mapeamento de eventos HubSpot

apps/integrations/hubspot/
└── client.py                    ← Métodos: assign_ticket_owner, get_ticket_details,
                                     get_team_members, search_tickets_in_novo_stage,
                                     count_active_tickets_by_owner, etc.

apps/webhooks/handlers/
└── hubspot_handler.py           ← Handlers para NOVO, FECHADO, owner change,
                                     availability change

core/settings/base.py           ← CELERY_BEAT_SCHEDULE, HUBSPOT_N1_TEAM_ID
```

---

## Concorrência e Locks

O sistema implementa múltiplas camadas de proteção contra race conditions:

### Database Level

| Mecanismo | Uso | Descrição |
|-----------|-----|-----------|
| `select_for_update(skip_locked=True)` | `matchmaker_assign_next()` | Previne que dois workers peguem o mesmo ticket |
| `transaction.atomic()` | Atribuições, fechamentos | Garante atomicidade das operações multi-tabela |
| `F()` expressions | `increment_agent_chat_count()` | Incremento atômico de contadores |
| `Greatest()` | `decrement_agent_chat_count()` | Decremento com floor em zero |

### Application Level (Redis)

| Lock Key | Timeout | Propósito |
|----------|---------|-----------|
| `matchmaker_claim:{ticket_id}` | 60s | Previne processamento duplicado do mesmo ticket |
| `matchmaker_assign:{ticket_id}` | 30s | Deduplicação de webhooks retries |
| `matchmaker_drain_lock` | 60s | Previne execução paralela de drain |

---

## Gestão de Agentes

### Adicionar Agente

1. Verificar se o agente existe no HubSpot com `hubspot_owner_id` correto
2. Inserir na tabela `agents`:
   ```sql
   INSERT INTO agents (hubspot_owner_id, name, agent_email, status_enum, auto_assign_enabled, is_active, max_simultaneous_chats)
   VALUES (12345678, 'Nome Agente', 'agente@empresa.com', 'offline', true, true, 5);
   ```

### Remover da Fila (temporário)

```sql
-- Desabilita atribuição automática (mantém no sistema)
UPDATE agents SET auto_assign_enabled = false WHERE hubspot_owner_id = 12345678;
```

### Desativar Agente (permanente)

```sql
-- Desativa completamente
UPDATE agents SET is_active = false WHERE hubspot_owner_id = 12345678;
```

### Sincronização Automática

A task `task_sync_hubspot_team_members` (diária 06:00) busca membros do time `HUBSPOT_N1_TEAM_ID` e cria automaticamente novos agentes na tabela `agents`.

---

## Configuração Inicial

### 1. Aplicar migrations

```bash
python manage.py migrate support
```

### 2. Configurar webhooks no HubSpot

Configure os seguintes webhooks na HubSpot App:

| Subscription | Propriedade | Handler |
|--------------|-------------|---------|
| `ticket.propertyChange` | `hs_v2_date_entered_939275049` | NOVO stage |
| `ticket.propertyChange` | `hs_v2_date_entered_939275052` | FECHADO stage |
| `ticket.propertyChange` | `hubspot_owner_id` | Owner change |
| `contact.propertyChange` | `hs_chat_transfer_availability` | Availability change |

### 3. Configurar Celery Beat

Adicione ao `CELERY_BEAT_SCHEDULE` em `settings/base.py`:

```python
CELERY_BEAT_SCHEDULE = {
    "sat_heartbeat": {
        "task": "support.task_sat_heartbeat",
        "schedule": 20.0,  # 20 segundos
    },
    "matchmaker_drain": {
        "task": "support.task_matchmaker_drain_queue",
        "schedule": 60.0,  # 60 segundos (safety net)
    },
    "sync_hubspot_team": {
        "task": "support.task_sync_hubspot_team_members",
        "schedule": crontab(hour=6, minute=0),
    },
    "aggregate_queue_metrics": {
        "task": "support.task_aggregate_queue_metrics",
        "schedule": crontab(hour=0, minute=5),
    },
    # ... outras tasks
}
```

### 4. Inicializar agentes

```bash
# Sync inicial do time N1
python manage.py shell -c "from apps.support.tasks import task_sync_hubspot_team_members; task_sync_hubspot_team_members()"

# Ou backfill completo de tickets NOVO
python manage.py shell -c "from apps.support.tasks import task_sync_novo_stage_tickets; task_sync_novo_stage_tickets()"
```

### 5. Verificar status do sistema

```bash
# Verificar fila
curl /api/v1/support/queue/status/

# Verificar agentes online
curl /api/v1/support/queue/agents/
```

---

## Troubleshooting

### Tickets não estão sendo atribuídos

**Sintoma:** `queue_eligible_agents count=0`

**Causas possíveis:**

1. **Nenhum agente ONLINE**
   - Verificar `agents.status_enum` — deve ser `'online'`
   - SAT heartbeat deve estar rodando (`task_sat_heartbeat`)
   - Verificar se agentes estão logados no HubSpot

2. **Todos os agentes atingiram capacidade**
   - Verificar `current_simultaneous_chats >= max_simultaneous_chats`
   - Task `task_reconcile_agent_counts` pode corrigir drift

3. **Agentes com `auto_assign_enabled = false`**
   - Verificar configuração na tabela `agents`

### Tickets acumulando na fila

**Diagnóstico:**
```python
# Verificar tickets pendentes
NewConversation.objects.filter(queue_status='queued').count()

# Verificar tentativas de atribuição
NewConversation.objects.filter(assignment_attempts__gt=0)
```

**Ações:**
- Executar `task_matchmaker_drain_queue()` manualmente
- Verificar logs por erros do HubSpot API
- Confirmar circuit breaker status

### Duplicação de atribuições

**Sintoma:** Mesmo ticket atribuído a múltiplos agentes

**Verificação:**
- Confirmar Redis está configurado e acessível
- Verificar locks `matchmaker_claim:{ticket_id}` estão sendo criados
- Confirmar `select_for_update(skip_locked=True)` está funcionando

### Drift de contagem de chats

**Sintoma:** `current_simultaneous_chats` diverge da realidade

**Correção:**
- Task `task_reconcile_agent_counts` executa reconciliação automática
- Ou executar manualmente via shell

---

## Logs de Referência

### Eventos de Sucesso

| Log Event | Nível | Descrição |
|-----------|-------|-----------|
| `sync_novo_stage_tickets_start` | INFO | Início do sync de tickets NOVO |
| `hubspot_novo_tickets_fetched` | INFO | Tickets buscados do HubSpot |
| `sync_novo_ticket_instanced` | INFO | Ticket criado na fila local |
| `sync_novo_stage_tickets_done` | INFO | Sync completado com estatísticas |
| `queue_eligible_agents` | DEBUG | Lista de agentes elegíveis |
| `queue_agent_selected` | INFO | Agente selecionado para atribuição |
| `matchmaker_assigned` | INFO | Atribuição bem-sucedida |
| `task_matchmaker_drain_queue_done` | INFO | Fila processada |

### Eventos de Skip/Warning

| Log Event | Nível | Causa |
|-----------|-------|-------|
| `sync_novo_ticket_has_owner_skipped` | DEBUG | Ticket já tem owner no HubSpot |
| `assign_pending_tickets_no_eligible_agents` | DEBUG | Sem agentes disponíveis |
| `matchmaker_no_agent_available` | INFO | Nenhum agente elegível no momento |
| `matchmaker_agent_at_capacity_after_reconcile` | INFO | Agente lotado após reconciliação |

### Eventos de Erro

| Log Event | Nível | Ação |
|-----------|-------|------|
| `auto_assign_hubspot_fetch_failed` | ERROR | Falha na API HubSpot (ticket details) |
| `matchmaker_hubspot_assign_failed` | ERROR | Falha ao atribuir owner no HubSpot |
| `sync_novo_stage_tickets_hubspot_fetch_failed` | ERROR | Falha no fetch batch de tickets |
