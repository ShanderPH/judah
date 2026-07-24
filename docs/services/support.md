# `apps.support` — Tickets, Filas e Auto-atribuição

## Resumo

Módulo mais complexo do JUDAH. Gerencia tickets de suporte, agentes, fila de atribuição automática (Matchmaker), rastreamento de disponibilidade (SAT), horário comercial e métricas de fila.

## Contexto

O `apps.support` substitui o Helper CX e parte do Backoffice. Ele reage a webhooks do HubSpot, atribui tickets a agentes disponíveis e mantém histórico de atribuições, reatribuições e fechamentos.

## Responsabilidades

- CRUD de tickets.
- Gerenciamento de agentes e suas capacidades.
- Fila de conversas pendentes (`NewConversation`).
- Algoritmo de seleção de agente.
- Sincronização de status e contadores com HubSpot (SAT).
- Cálculo de métricas de fila e agente.
- Horário comercial e agendas especiais.

## Modelos principais

### `Agent`

Representa um atendente humano.

| Campo | Descrição |
|-------|-----------|
| `hubspot_owner_id` | ID do owner no HubSpot |
| `agent_email` | Email do agente (único) |
| `status_enum` | `online`, `away`, `offline`, `busy` |
| `current_simultaneous_chats` | Chats atuais |
| `max_simultaneous_chats` | Capacidade máxima |
| `auto_assign_enabled` | Participa da auto-atribuição |
| `working_hours`, `skills`, `timezone` | Configurações |
| `online_time_seconds_today` / `away_time_seconds_today` | Acumuladores diários |

### `Ticket`

Ticket de suporte mapeado da tabela legada `tickets`.

### `NewConversation`

Ticket aguardando atribuição automática.

### `AssignedConversation`

Ticket atribuído a um agente.

### `ClosedConversation`

Ticket fechado, com métricas.

### `AssignmentLog`

Log de cada ação de atribuição.

### `ConversationReassignment`

Registro de transferência entre agentes.

### `QueuePerformanceMetrics`

Métricas diárias da fila.

### `AgentMetrics` / `AgentDailyTimeLog`

Métricas e logs de tempo dos agentes.

### `BusinessHoursConfig` / `SpecialSchedule`

Configuração de horário comercial e exceções.

## Services principais

| Service | Arquivo | Responsabilidade |
|---------|---------|------------------|
| CRUD de tickets | `services.py` | `get_ticket`, `list_tickets`, `create_ticket`, `update_ticket` |
| Auto-atribuição | `auto_assign_service.py` | `process_new_ticket_event`, `attempt_auto_assign`, `handle_ticket_closed`, `sync_novo_stage_tickets` |
| Matchmaker | `matchmaker_service.py` | `matchmaker_assign_next`, `matchmaker_drain_queue`, `enqueue_new_ticket` |
| Seleção de agente | `queue_service.py` | `select_next_agent`, `get_eligible_agents`, `increment_agent_chat_count`, `decrement_agent_chat_count` |
| SAT | `sat_service.py` | `sat_heartbeat`, `sat_reconcile_agent_load`, `sat_accumulate_time`, `sat_reset_daily_counters` |
| Sync de agentes | `agent_sync_service.py` | `is_business_hours`, `sync_all_agents_status_and_counts_optimized` |
| Admin | `admin_api.py` | CRUD de agentes, métricas, reatribuição manual |

## Tasks Celery

| Task | Schedule | Descrição |
|------|----------|-----------|
| `task_sat_heartbeat` | 20s | Sincroniza availability dos agentes |
| `task_sat_reset_daily_counters` | 00:01 | Reseta contadores diários |
| `task_matchmaker_drain_queue` | 60s | Processa fila pendente |
| `task_matchmaker_assign_single` | On-demand | Atribui ticket específico |
| `task_handle_ticket_closed` | On-demand | Processa fechamento |
| `task_handle_owner_change` | On-demand | Processa reatribuição |
| `task_matchmaker_assign_single` | Webhook de ticket NOVO | Enfileira, consulta Users API sem cache e só então tenta atribuir |
| `task_sync_hubspot_team_members` | 06:00 | Sincroniza time N1 |
| `task_sync_novo_stage_tickets` | 08:00 + startup | Sincroniza tickets NOVO |
| `task_aggregate_queue_metrics` | 00:05 | Agrega métricas de fila |
| `task_aggregate_agent_metrics` | 00:10 | Agrega métricas por agente |
| `task_reconcile_agent_counts` | :30 de cada hora | Reconcilia contadores com HubSpot |

## Endpoints

Base: `/api/v1/support/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| GET/POST | `/tickets/` | JWT | Lista / cria tickets |
| GET/PATCH | `/tickets/{ticket_id}` | JWT | Detalhe / atualiza ticket |
| GET | `/queue/status/` | JWT | Status da fila |
| GET | `/queue/pending/` | JWT | Conversas pendentes |
| GET | `/queue/assigned/` | JWT | Conversas atribuídas |
| GET | `/queue/health/` | JWT | Diagnóstico da fila |
| POST | `/queue/sync-novo/` | — | Sincroniza tickets NOVO |
| GET | `/queue/metrics/` | JWT | Métricas de fila |
| GET | `/business-hours/` | — | Horário comercial |
| GET/POST | `/special-schedules/` | — | Agenda especial |
| DELETE | `/special-schedules/{id}` | — | Remove agenda especial |
| GET/POST | `/agents/` | JWT (manager+) | Lista / cria agentes |
| GET/PATCH | `/agents/{id}` | JWT (manager+) | Detalhe / atualiza agente |
| POST | `/agents/{id}/inactivate` | JWT (manager+) | Inativa agente |
| POST | `/agents/{id}/reactivate` | JWT (manager+) | Reativa agente |
| POST | `/queue/manual-assign/` | JWT (manager+) | Atribuição manual |
| POST | `/queue/force-reassign/` | JWT (manager+) | Reatribuição forçada |

## Regras de negócio

- Ticket elegível para auto-atribuição: pipeline `636459134`, sem owner.
- Agente elegível: online, auto_assign_enabled, ativo, abaixo da capacidade.
- Seleção: online → evitar último atribuído → maior tempo ocioso → menor carga.
- Fechamento: decrementa contador do agente atribuído, não de quem fechou.
- Fora do horário comercial, SAT não faz chamadas HubSpot.

## Arquivos relacionados

- [`apps/support/models.py`](../../apps/support/models.py)
- [`apps/support/api.py`](../../apps/support/api.py)
- [`apps/support/admin_api.py`](../../apps/support/admin_api.py)
- [`apps/support/tasks.py`](../../apps/support/tasks.py)
- [`apps/support/queue_service.py`](../../apps/support/queue_service.py)
- [`apps/support/matchmaker_service.py`](../../apps/support/matchmaker_service.py)
- [`apps/support/auto_assign_service.py`](../../apps/support/auto_assign_service.py)
- [`apps/support/sat_service.py`](../../apps/support/sat_service.py)
- [`apps/support/agent_sync_service.py`](../../apps/support/agent_sync_service.py)

## Pontos de atenção

- `Ticket.status` e `Ticket.priority` são textos livres (sem enum).
- `NewConversation.queue_position` é calculado dinamicamente (pode ser lento com fila grande).
- A função `services.get_ticket` usava sintaxe `except Ticket.DoesNotExist, ValueError:` (Python 2). **Corrigida** para `except (Ticket.DoesNotExist, ValueError):`.
- **Cuidado:** `ruff format` (v0.15.8) tenta reverter a sintaxe corrigida para a forma Python 2. Não execute `ruff format` neste arquivo até que o comportamento seja investigado.
- Verificar se `auto_assign_service.py` e `hubspot_handler.py` ainda contêm alguma sintaxe de exceção no estilo Python 2.

## Recomendações

- Converter `Ticket.status` e `Ticket.priority` para enums.
- Materializar `queue_position` ou usar row_number no banco.
- Corrigir a sintaxe de `except` em `services.get_ticket`.
- Adicionar testes para todos os fluxos de auto-atribuição.
