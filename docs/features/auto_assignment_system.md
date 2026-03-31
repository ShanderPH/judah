# Auto-Assignment System — Fila de Atendimento Automático

## Visão Geral

Sistema completo de atribuição automática de tickets HubSpot para agentes de suporte N1,
com fila de atendimento ranqueada, metrificação de tempos de espera e rastreamento de
encerramento de atendimentos.

---

## Arquitetura

```
HubSpot Webhook
    │
    ▼
POST /api/v1/webhooks/hubspot/           ← WebhookEvent registrado
    │
    ▼
hubspot_handler._handle_ticket_entered_novo()
    │
    ▼ (Celery task: task_process_new_ticket_event)
    │
    ▼
auto_assign_service.process_new_ticket_event()
    │   1. Busca detalhes do ticket na HubSpot API
    │   2. Valida pipeline (636459134) e ausência de owner
    │   3. Cria registro em new_conversations
    │
    ▼
queue_service.select_next_agent()
    │   Aplica regras de prioridade (ver abaixo)
    │
    ▼
HubSpotClient.assign_ticket_owner()      ← Atualiza hubspot_owner_id via API
    │
    ▼
DB: new_conversations (is_pending=False)
    assigned_conversations (novo registro)
    assignment_logs (auditoria)
    agents (current_simultaneous_chats++)
```

---

## Regras de Prioridade da Fila (ordem decrescente de importância)

| # | Regra |
|---|-------|
| 1 | Somente agentes com `status_enum = ONLINE` participam da fila |
| 2 | Nunca atribuir dois atendimentos consecutivos ao mesmo agente (exceto se for o único online) |
| 3 | Preferência para o agente com maior tempo desde o último atendimento (`last_assignment_at` nulo = maior prioridade) |
| 4 | Entre agentes empatados, preferência para o com menos chats simultâneos; agentes que atingiram `max_simultaneous_chats` são excluídos |

---

## Tabelas de Banco de Dados

### `new_conversations`
Tickets que entraram no estágio NOVO e aguardam atribuição.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `hubspot_ticket_id` | TEXT UNIQUE | ID do ticket no HubSpot |
| `pipeline_id` | TEXT | Pipeline (padrão: 636459134) |
| `entered_queue_at` | TIMESTAMPTZ | Valor de `hs_v2_date_entered_939275049` |
| `is_pending` | BOOLEAN | TRUE = aguardando, FALSE = atribuído |

### `assigned_conversations`
Tickets atribuídos pelo sistema automático.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `hubspot_ticket_id` | TEXT UNIQUE | ID do ticket |
| `agent_id` | UUID FK | Agente atribuído (local DB) |
| `hubspot_owner_id` | BIGINT | ID do owner no HubSpot |
| `entered_queue_at` | TIMESTAMPTZ | Quando entrou na fila |
| `assigned_at` | TIMESTAMPTZ | Quando foi atribuído |
| `queue_wait_seconds` | NUMERIC | Tempo de espera na fila (segundos) |
| `closed_at` | TIMESTAMPTZ | Quando o atendimento foi encerrado |
| `total_handle_time_minutes` | NUMERIC | Tempo total de atendimento |

### `queue_performance_metrics`
Métricas diárias agregadas da fila.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `metric_date` | DATE UNIQUE | Data da métrica |
| `total_entered_queue` | INT | Tickets que entraram na fila |
| `total_assigned` | INT | Atribuições realizadas |
| `total_closed` | INT | Atendimentos encerrados |
| `avg_queue_wait_seconds` | NUMERIC | Tempo médio de espera (segundos) |
| `p50_queue_wait_seconds` | NUMERIC | Mediana do tempo de espera |
| `p95_queue_wait_seconds` | NUMERIC | Percentil 95 do tempo de espera |
| `avg_handle_time_minutes` | NUMERIC | Tempo médio de atendimento |
| `assignments_by_agent` | JSONB | Atribuições por agente `{owner_id: count}` |

### `assignment_logs` (existente, estendida)
Colunas adicionadas: `queue_wait_seconds`, `entered_queue_at`, `pipeline_id`.

---

## Triggers do Webhook HubSpot

| Propriedade | Evento | Ação |
|-------------|--------|------|
| `hs_v2_date_entered_939275049` | Ticket → NOVO | Enfileira e atribui automaticamente |
| `hs_v2_date_entered_939275052` | Ticket → FECHADO | Registra encerramento e calcula tempo total |
| `hs_pipeline_stage` | Mudança de estágio | Atualiza status local (legado) |

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

| Task | Schedule | Descrição |
|------|----------|-----------|
| `support.task_process_new_ticket_event` | On-demand | Processa um ticket novo (com retry automático) |
| `support.task_handle_ticket_closed` | On-demand | Registra encerramento de atendimento |
| `support.task_sync_hubspot_team_members` | Diário 06:00 | Sincroniza membros do time N1 com a tabela agents |
| `support.task_aggregate_queue_metrics` | Diário 00:05 | Agrega métricas do dia anterior |

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

```
apps/support/
├── models.py              ← + NewConversation, AssignedConversation,
│                              QueuePerformanceMetrics, AssignmentLog
├── migrations/
│   └── 0002_auto_assignment_tables.py   ← nova migration
├── queue_service.py        ← NOVO — algoritmo de seleção de agentes
├── auto_assign_service.py  ← NOVO — orquestração da atribuição automática
├── tasks.py                ← NOVO — tarefas Celery
├── schemas.py              ← + schemas de fila (queue, assigned, metrics)
└── api.py                  ← + 4 novos endpoints de fila

apps/integrations/hubspot/
└── client.py               ← + assign_ticket_owner, get_ticket_details,
                                 get_team_members, get_owner_details

apps/webhooks/handlers/
└── hubspot_handler.py      ← Atualizado para processar NOVO e FECHADO

core/settings/base.py       ← + CELERY_BEAT_SCHEDULE, HUBSPOT_N1_TEAM_ID
```

---

## Configuração Inicial

1. Aplicar migration:
   ```bash
   python manage.py migrate support
   ```

2. Configurar webhook no HubSpot para disparar em:
   - `ticket.propertyChange` → `hs_v2_date_entered_939275049`
   - `ticket.propertyChange` → `hs_v2_date_entered_939275052`

3. Confirmar agentes na tabela `agents` com `hubspot_owner_id` correto e `status_enum = 'online'`.

4. (Opcional) Executar sync inicial do time:
   ```bash
   python manage.py shell -c "from apps.support.tasks import task_sync_hubspot_team_members; task_sync_hubspot_team_members()"
   ```
