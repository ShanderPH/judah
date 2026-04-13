# Sistema de Atribuição Automática e Fila de Atendimento - Documentação Técnica Completa

## 1. Visão Geral do Sistema

### 1.1 Propósito e Contexto

O sistema de atribuição automática e fila de atendimento (Auto-Assignment System) é um componente crítico da plataforma JUDAH, responsável por distribuir tickets de suporte HubSpot para agentes de N1 de forma automatizada, justa e eficiente. O sistema opera como um middleware inteligente entre o HubSpot CRM e a equipe de suporte, garantindo que tickets sejam atribuídos ao agente mais adequado disponível.

### 1.2 Arquitetura de Alto Nível

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HUBSPOT CRM                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Ticket    │  │   Ticket    │  │   Ticket    │  │   Agent Availability │  │
│  │  Created    │  │  → NOVO     │  │  → FECHADO  │  │     (Users API)      │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
└─────────┼────────────────┼────────────────┼──────────────────────────────────┘
          │                │                │
          │ Webhook        │ Webhook        │ Webhook
          │ (propertyChange)│ (propertyChange)│ (propertyChange)
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         JUDAH WEBHOOK HANDLER                                │
│                    apps/webhooks/handlers/hubspot_handler.py                 │
│                                                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────────┐  │
│  │ _handle_ticket_entered_ │  │ _handle_ticket_entered_closed           │  │
│  │ _novo()                 │  │ ()                                      │  │
│  │                         │  │                                         │  │
│  │ Triggers:               │  │ Triggers:                               │  │
│  │ hs_v2_date_entered_     │  │ hs_v2_date_entered_                     │  │
│  │ 939275049               │  │ 939275052                               │  │
│  └───────────┬─────────────┘  └───────────────────┬─────────────────────┘  │
│              │                                    │                         │
│              ▼                                    ▼                         │
│  ┌─────────────────────────┐  ┌─────────────────────────────────────────┐  │
│  │ process_new_ticket_     │  │ handle_ticket_closed()                  │  │
│  │ event()                 │  │                                         │  │
│  └───────────┬─────────────┘  └─────────────────────────────────────────┘  │
└──────────────┼──────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AUTO-ASSIGNMENT ORCHESTRATION                           │
│                    apps/support/auto_assign_service.py                       │
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐   │
│  │  1. Validation  │───▶│  2. Enqueue     │───▶│  3. Select Agent   │   │
│  │                 │    │                 │    │     (4 Rules)      │   │
│  │ - Pipeline check│    │ new_conversations│   │                     │   │
│  │ - Owner check   │    │                 │    │ queue_service.py   │   │
│  └─────────────────┘    └─────────────────┘    └──────────┬──────────┘   │
│                                                          │                │
│               ┌──────────────────────────────────────────┘                │
│               ▼                                                           │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────┐  │
│  │  4. HubSpot Assignment  │───▶│  5. Local DB State Update            │  │
│  │                         │    │                                     │  │
│  │ HubSpotClient.assign_   │    │ - assigned_conversations (create)  │  │
│  │ ticket_owner()          │    │ - assignment_logs (audit)           │  │
│  │                         │    │ - agents (chat_count++)             │  │
│  │                         │    │ - new_conversations (delete)        │  │
│  └─────────────────────────┘    └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Componentes Principais

| Componente | Arquivo | Responsabilidade |
|------------|---------|------------------|
| **Webhook Handler** | `apps/webhooks/handlers/hubspot_handler.py` | Recebe e roteia eventos HubSpot |
| **Auto-Assignment Service** | `apps/support/auto_assign_service.py` | Orquestra todo o fluxo de atribuição |
| **Queue Service** | `apps/support/queue_service.py` | Algoritmo de seleção de agentes (4 regras) |
| **HubSpot Client** | `apps/integrations/hubspot/client.py` | Integração com APIs HubSpot |
| **Celery Tasks** | `apps/support/tasks.py` | Tarefas assíncronas e agendadas |
| **Models** | `apps/support/models.py` | Definição de entidades e relacionamentos |
| **API Endpoints** | `apps/support/api.py` | Endpoints REST para monitoramento |

---

## 2. Lógica de Atribuição Automática

### 2.1 Fluxo de Processamento de Novo Ticket

```
┌─────────────────┐
│  Ticket entra   │
│  em NOVO        │
│  (HubSpot)      │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  1. process_new_ticket_event()          │
│                                         │
│  - Extrai hubspot_ticket_id             │
│  - Parse do timestamp entered_at_ms     │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  2. Busca detalhes no HubSpot           │
│     get_ticket_details()                │
│                                         │
│  Props buscadas:                          │
│  - subject, hs_ticket_priority          │
│  - hs_pipeline, hs_pipeline_stage     │
│  - hubspot_owner_id                     │
│  - hs_v2_date_entered_939275049         │
│  - firstname, email (contato)           │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  3. Validação (_is_ticket_eligible)     │
│                                         │
│  REGRA 1: Pipeline == 636459134          │
│  REGRA 2: owner_id deve estar vazio     │
│                                         │
│  Se falhar: ABORTA (retorna False)      │
└────────┬────────────────────────────────┘
         │ Válido
         ▼
┌─────────────────────────────────────────┐
│  4. Enfileiramento                      │
│     NewConversation.objects             │
│     .get_or_create()                    │
│                                         │
│  - Idempotente: não duplica tickets     │
│  - Preserva entered_queue_at original   │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  5. Tentativa de Atribuição             │
│     attempt_auto_assign()               │
│                                         │
│  (Ver seção 2.2)                        │
└─────────────────────────────────────────┘
```

### 2.2 Algoritmo de Seleção de Agentes (4 Regras)

O algoritmo de seleção implementado em `queue_service.select_next_agent()` segue uma hierarquia rigorosa de prioridades:

#### Regra 1: Status Online (Filtro Principal)

```python
def get_eligible_agents() -> list[Agent]:
    agents = Agent.objects.filter(
        status_enum=Agent.StatusEnum.ONLINE,    # APENAS ONLINE
        auto_assign_enabled=True,               # Auto-assign ativado
    ).exclude(is_active=False)                  # Agente ativo

    # Filtra agentes em capacidade máxima
    eligible = [a for a in agents if a.current_simultaneous_chats < (a.max_simultaneous_chats or 5)]
```

- **ONLINE**: Agente disponível para receber tickets
- **AWAY**: Agente ausente (não recebe)
- **OFFLINE**: Agente desconectado (não recebe)
- **BUSY**: Agente ocupado (não recebe)

#### Regra 2: Sem Atribuições Consecutivas

```python
# Se há mais de 1 agente elegível, exclui o último atribuído
if last_assigned_hubspot_owner_id is not None and len(eligible) > 1:
    candidates = [a for a in eligible if a.hubspot_owner_id != last_assigned_hubspot_owner_id]
```

- **Objetivo**: Distribuir carga uniformemente entre agentes
- **Fallback**: Se só há 1 agente online, a regra é ignorada

#### Regra 3: Maior Tempo Desde Última Atribuição

```python
# NULL last_assignment_at = maior prioridade (nunca atribuído)
_epoch = timezone.datetime(2000, 1, 1, tzinfo=UTC)

def _sort_key(agent: Agent) -> tuple:
    last = agent.last_assignment_at or _epoch  # NULL → epoch (prioridade máxima)
    if timezone.is_naive(last):
        last = timezone.make_aware(last, UTC)
    return (last, agent.current_simultaneous_chats)
```

- **Objetivo**: Round-robin justo baseado em histórico
- **Prioridade máxima**: Agentes que nunca receberam tickets

#### Regra 4: Menor Carga Atual

```python
# Segundo critério de ordenação: current_simultaneous_chats ASC
return (last, agent.current_simultaneous_chats)
```

- **Objetivo**: Balanceamento de carga em tempo real
- **Exclusão**: Agentes em capacidade máxima são filtrados na Regra 1

#### Diagrama de Decisão do Algoritmo

```
┌─────────────────────────────────────────────────────────────────┐
│                     SELECT_NEXT_AGENT()                         │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  get_eligible_agents  │
              │  (Regra 1: ONLINE)    │
              └───────────┬───────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        ┌─────────┐             ┌─────────┐
        │ Vazio?  │             │  Lista  │
        │  Sim    │             │ Agentes │
        └────┬────┘             └────┬────┘
             │                       │
             ▼                       ▼
    ┌─────────────────┐    ┌─────────────────────┐
    │  Retorna None   │    │  Aplicar Regra 2:   │
    │  (fila bloqueada)│    │  Excluir último     │
    └─────────────────┘    │  atribuído (se >1)  │
                           └──────────┬──────────┘
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │  Aplicar Regra 3+4: │
                           │  Sort por:          │
                           │  (last_assignment, │
                           │   current_chats)    │
                           └──────────┬──────────┘
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │  Retorna candidates[0]│
                           │  (melhor agente)    │
                           └─────────────────────┘
```

### 2.3 Sincronização Pré-Atribuição

Antes de cada atribuição, o   sistema realiza uma sincronização paralela para garantir dados atualizados:

```python
def attempt_auto_assign(new_conv: NewConversation, ticket_data: dict | None = None) -> bool:
    # 1. Sync de status e contagens de TODOS os agentes
    sync_all_agents_status_and_counts()

    # 2. Seleciona agente com dados atualizados
    agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner)

    # 3. Double-check: verifica se ainda está disponível
    agent.refresh_from_db()
    if agent.status_enum != Agent.StatusEnum.ONLINE:
        # Re-seleciona com dados atualizados
        agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner)
```

**Operações de Sync (Paralelas com ThreadPoolExecutor):**

| Operação | Fonte | Propsósito |
|----------|-------|------------|
| `get_all_owners_availability()` | HubSpot Users API | Status online/away |
| `count_active_tickets_by_owner()` | HubSpot Tickets Search | Contagem real de tickets ativos |

---

## 3. Gerenciamento da Fila

### 3.1 Estados do Ticket na Fila

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│    NOVO       │      │    QUEUED       │      │   ASSIGNED      │
│   (Entry)       │─────▶│  (No Agent)     │─────▶│   (Active)      │
│                 │      │                 │      │                 │
│ - entered_queue │      │ - assignment_   │      │ - assigned_at   │
│   _at           │      │   attempts++    │      │ - agent_id      │
│ - pending       │      │ - last_attempt_ │      │ - queue_wait_   │
│                 │      │   at            │      │   seconds       │
└─────────────────┘      └─────────────────┘      └────────┬────────┘
                                                             │
                                                             ▼
                                                    ┌─────────────────┐
                                                    │    CLOSED       │
                                                    │   (Final)       │
                                                    │                 │
                                                    │ - closed_at     │
                                                    │ - total_handle_ │
                                                    │   time_minutes  │
                                                    └─────────────────┘
```

### 3.2 Ordenação da Fila (FIFO)

```python
class NewConversation(models.Model):
    class Meta:
        ordering = ["entered_queue_at"]  # Mais antigo primeiro

    @property
    def queue_position(self) -> int:
        """Posição 1-indexed na fila"""
        return NewConversation.objects.filter(
            entered_queue_at__lt=self.entered_queue_at
        ).count() + 1
```

### 3.3 Processamento de Tickets Pendentes

Quando um agente fica online, o sistema processa tickets acumulados:

```python
def assign_pending_tickets() -> dict:
    """Tenta atribuir todos os tickets pendentes (FIFO)."""
    pending = list(NewConversation.objects.all().order_by("entered_queue_at"))

    for conv in pending:
        # Verifica se ainda há agentes elegíveis
        if not get_eligible_agents():
            skipped += remaining
            break

        success = attempt_auto_assign(conv)
        if success:
            assigned += 1
        else:
            skipped += 1
```

### 3.4 Concorrência e Race Conditions

O sistema implementa várias estratégias para lidar com concorrência:

| Estratégia | Implementação | Propósito |
|------------|-------------|-----------|
| **Atomic Updates** | `Agent.objects.filter(pk=agent.pk).update(...)` | Incremento/decremento atômico de contadores |
| **Database Transactions** | `@transaction.atomic()` | Consistência em movimentação de registros |
| **Pre-assignment Sync** | `sync_all_agents_status_and_counts()` | Previne atribuição a agentes indisponíveis |
| **Double-Check Pattern** | `agent.refresh_from_db()` | Validação pós-sync antes de commit |

---

## 4. Fluxo End-to-End

### 4.1 Sequence Diagram: Novo Ticket → Atribuição

```
HubSpot          Webhook Handler         Auto-Assign Service        Queue Service       HubSpot Client         Database
  │                      │                         │                    │                   │                 │
  │─Ticket entra NOVO────▶│                         │                    │                   │                 │
  │                      │                         │                    │                   │                 │
  │                      │─_handle_ticket_entered_novo()──────────────▶│                   │                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─process_new_ticket_event()              │                 │
  │                      │                         │                    │                   │                 │
  │◀────get_ticket_details()───────────────────────────────────────────▶│                 │
  │                      │                         │                    │                   │                 │
  │────Ticket data──────────────────────────────────────────────────────▶│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─_is_ticket_eligible()                 │                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─NewConversation.get_or_create()─────────────▶│            │
  │                      │                         │                    │                   │                 │
  │                      │                         │─attempt_auto_assign()                 │                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─sync_all_agents_status_and_counts()     │                 │
  │                      │                         │                    │                   │                 │
  │◀────get_all_owners_availability()────────────────────────────────────▶│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │──count_active_tickets_by_owner()───────▶│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─select_next_agent()▶│                   │                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │◀────get_eligible_agents()─────────────│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │◀────Agent selecionado───────────────────│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─assign_ticket_owner()─────────────────▶│                │
  │                      │                         │                    │                   │                 │
  │                      │                         │◀────Assignment confirmed───────────────│                 │
  │                      │                         │                    │                   │                 │
  │                      │                         │─transaction.atomic()────────────────────────────────▶      │
  │                      │                         │                    │                   │                 │
  │                      │                         │  ├─new_conv.delete()                                    │
  │                      │                         │  ├─AssignedConversation.objects.update_or_create()      │
  │                      │                         │  ├─AssignmentLog.objects.create()                       │
  │                      │                         │  └─increment_agent_chat_count()                         │
  │                      │                         │                    │                   │                 │
  │                      │                         │◀─────────────────────────────────────────────────────────│
  │                      │                         │                    │                   │                 │
  │                      │◀────────────────────────│                    │                   │                 │
  │                      │                         │                    │                   │                 │
```

### 4.2 Sequence Diagram: Fechamento de Ticket

```
HubSpot          Webhook Handler         Auto-Assign Service        Queue Service         Database
  │                      │                         │                    │                   │
  │─Ticket → FECHADO─────▶│                         │                    │                   │
  │                      │                         │                    │                   │
  │                      │─_handle_ticket_entered_closed()─────────────▶│                   │
  │                      │                         │                    │                   │
  │                      │                         │─handle_ticket_closed()                │
  │                      │                         │                    │                   │
  │                      │                         │─NewConversation.objects.filter().first()────────────▶│
  │                      │                         │                    │                   │
  │                      │                         │─pending_conv.delete() (se existir)───────────────▶│
  │                      │                         │                    │                   │
  │                      │                         │─AssignedConversation.objects.get()─────────────▶│
  │                      │                         │                    │                   │
  │                      │                         │─transaction.atomic()────────────────────────────────▶│
  │                      │                         │  ├─ClosedConversation.objects.get_or_create()       │
  │                      │                         │  ├─assigned.delete()                                  │
  │                      │                         │  └─decrement_agent_chat_count()────────────────────▶│
  │                      │                         │                    │                   │
  │                      │                         │◀─────────────────────────────────────────────────────│
  │                      │                         │                    │                   │
  │                      │◀────────────────────────│                    │                   │
```

---

## 5. Regras de Negócio

### 5.1 Regras de Validação de Ticket

| Regra | Condição | Ação em Caso de Falha |
|-------|----------|----------------------|
| Pipeline correto | `pipeline == 636459134` | Ignora ticket (log: `auto_assign_ticket_wrong_pipeline`) |
| Sem owner | `owner_id` vazio/null/None | Ignora ticket (log: `auto_assign_ticket_already_has_owner`) |

### 5.2 Regras de Elegibilidade de Agente

| Regra | Condição | Descrição |
|-------|----------|-----------|
| Status online | `status_enum == ONLINE` | Apenas agentes disponíveis |
| Auto-assign habilitado | `auto_assign_enabled == True` | Respeita configuração individual |
| Agente ativo | `is_active != False` | Não considera agentes desativados |
| Capacidade disponível | `current_chats < max_chats` | Respeita limite de chats simultâneos |

### 5.3 Regras de Atribuição

| Regra | Prioridade | Descrição |
|-------|------------|-----------|
| No consecutivo | 2 | Não atribuir ao mesmo agente consecutivamente (se >1 elegível) |
| Round-robin | 3 | Priorizar agente com maior tempo desde última atribuição |
| Carga balanceada | 4 | Entre empatados, preferir menor carga atual |

### 5.4 Regras de Reatribuição (Manual)

Quando um ticket é transferido manualmente no HubSpot:

```python
# 1. Decrementa contador do agente anterior
decrement_agent_chat_count(from_agent)

# 2. Incrementa contador do novo agente
increment_agent_chat_count(to_agent)

# 3. Atualiza registro em assigned_conversations
assigned_conv.agent = to_agent

# 4. Registra a transferência
ConversationReassignment.objects.create(
    hubspot_ticket_id=hubspot_ticket_id,
    from_agent=from_agent,
    to_agent=to_agent,
    time_with_previous_agent_seconds=delta,
)
```

---

## 6. Modelos de Dados e Dependências

### 6.1 Diagrama Entidade-Relacionamento

```
┌─────────────────────┐
│       Agent         │
├─────────────────────┤
│ id (PK)             │
│ name                │
│ agent_email (UQ)    │
│ hubspot_owner_id    │
│ status_enum         │ ◄── online, away, offline, busy
│ current_simultaneous│
│ _chats              │
│ max_simultaneous_   │
│   chats             │
│ auto_assign_enabled │
│ is_active           │
│ last_assignment_at  │
└─────────┬───────────┘
          │
          │ 1:N
          ▼
┌─────────────────────┐         ┌─────────────────────┐
│ AssignedConversation│         │  AgentStatusHistory │
├─────────────────────┤         ├─────────────────────┤
│ id (PK)             │         │ id (PK)             │
│ hubspot_ticket_id   │         │ agent_id (FK)       │
│ agent_id (FK) ──────┼─────────┤ old_status          │
│ hubspot_owner_id    │         │ new_status          │
│ entered_queue_at    │         │ changed_at          │
│ assigned_at         │         │ sync_source         │
│ queue_wait_seconds  │         └─────────────────────┘
│ closed_at           │
│ total_handle_time_  │
│   minutes           │
└─────────┬───────────┘
          │
          │ (move on close)
          ▼
┌─────────────────────┐
│ ClosedConversation  │
├─────────────────────┤
│ id (PK)             │
│ hubspot_ticket_id   │
│ agent_id (FK)       │
│ hubspot_owner_id    │
│ closed_at           │
│ queue_wait_seconds  │
│ total_handle_time_  │
│   minutes           │
└─────────────────────┘

┌─────────────────────┐
│  NewConversation    │
├─────────────────────┤
│ id (PK)             │
│ hubspot_ticket_id   │
│ entered_queue_at    │
│ queue_status        │ ◄── pending, queued
│ assignment_attempts │
│ last_assignment_    │
│   attempt_at        │
└─────────────────────┘

┌─────────────────────┐         ┌─────────────────────────────┐
│   AssignmentLog     │         │ ConversationReassignment  │
├─────────────────────┤         ├─────────────────────────────┤
│ id (PK)             │         │ id (PK)                     │
│ ticket_id           │         │ hubspot_ticket_id           │
│ agent_id (FK)       │         │ from_agent_id (FK)          │
│ hubspot_owner_id    │         │ to_agent_id (FK)            │
│ assignment_type     │         │ reassigned_at               │
│ queue_wait_seconds  │         │ time_with_previous_agent_   │
│ entered_queue_at    │         │   seconds                   │
│ assigned_at         │         └─────────────────────────────┘
└─────────────────────┘

┌─────────────────────┐
│QueuePerformanceMetrics│
├─────────────────────┤
│ id (PK)             │
│ metric_date (UQ)    │
│ total_entered_queue │
│ total_assigned      │
│ total_closed        │
│ avg_queue_wait_     │
│   seconds           │
│ p50_queue_wait_     │
│   seconds           │
│ p95_queue_wait_     │
│   seconds           │
│ assignments_by_agent│
└─────────────────────┘
```

### 6.2 Dependências de Serviços

| Serviço | Dependência | Tipo | Descrição |
|---------|-------------|------|-----------|
| Auto-Assignment | HubSpot CRM API | Síncrona | Busca de tickets, atribuição de owner |
| Auto-Assignment | HubSpot Users API | Síncrona | Sync de disponibilidade |
| Auto-Assignment | Supabase/PostgreSQL | Síncrona | Persistência de estado |
| Auto-Assignment | Celery + Redis | Assíncrona | Tarefas de background |

---

## 7. Tratamento de Falhas

### 7.1 Estratégias de Retry

| Componente | Estratégia | Max Retries | Delay |
|------------|------------|-------------|-------|
| `task_process_new_ticket_event` | Exponencial backoff | 3 | 30s |
| `task_handle_ticket_closed` | Exponencial backoff | 3 | 30s |
| `task_sync_novo_stage_tickets` | Exponencial backoff | 3 | 60s |
| HubSpot API | Circuit breaker | N/A | 60s recovery |

### 7.2 Circuit Breaker

```python
_circuit_breaker = CircuitBreaker(
    name="hubspot",
    failure_threshold=5,      # Abre após 5 falhas
    recovery_timeout=60       # Tenta fechar após 60s
)
```

### 7.3 Falhas de Atribuição e Fila de Espera

```python
def attempt_auto_assign(new_conv: NewConversation, ...) -> bool:
    agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner)

    if agent is None:
        # Nenhum agente disponível - mantém na fila
        new_conv.queue_status = NewConversation.QueueStatus.QUEUED
        new_conv.assignment_attempts += 1
        new_conv.last_assignment_attempt_at = timezone.now()
        new_conv.save(...)
        return False
```

**Comportamento:**
- Ticket permanece em `new_conversations`
- Status atualizado para `queued`
- Contador de tentativas incrementado
- Será reprocessado quando agente ficar online

### 7.4 Fallbacks

| Cenário | Fallback | Implementação |
|---------|----------|---------------|
| Sync de status falha | Usar dados em cache | `except Exception: continue` |
| Apenas 1 agente online | Ignorar Regra 2 | `if len(eligible) > 1: exclude last` |
| Agent indisponível após sync | Re-selecionar | `agent.refresh_from_db(); re-select` |

---

## 8. Observabilidade

### 8.1 Estrutura de Logging (structlog)

Todos os logs seguem formato estruturado JSON em produção:

```json
{
  "event": "auto_assign_success",
  "timestamp": "2026-01-15T14:32:10Z",
  "level": "info",
  "logger": "apps.support.auto_assign_service",
  "ticket_id": "12345678",
  "agent_name": "João Silva",
  "hubspot_owner_id": 98765,
  "queue_wait_seconds": 4.5
}
```

### 8.2 Eventos Principais Logados

| Evento | Nível | Local | Contexto |
|--------|-------|-------|----------|
| `auto_assign_new_ticket_event` | info | `auto_assign_service` | Início do processamento |
| `auto_assign_success` | info | `auto_assign_service` | Atribuição concluída |
| `auto_assign_no_agent_available` | warning | `auto_assign_service` | Fila bloqueada |
| `queue_agent_selected` | info | `queue_service` | Agente escolhido |
| `queue_no_eligible_agents` | warning | `queue_service` | Sem agentes disponíveis |
| `hubspot_ticket_owner_assigned` | info | `hubspot/client` | Confirmação HubSpot |
| `agent_status_updated_via_webhook` | info | `hubspot_handler` | Mudança de status |

### 8.3 Endpoints de Monitoramento

| Endpoint | Propósito |
|----------|-----------|
| `GET /api/v1/support/queue/status/` | Snapshot rápido da fila |
| `GET /api/v1/support/queue/health/` | Diagnóstico completo com alertas |
| `GET /api/v1/support/queue/pending/` | Lista tickets aguardando |
| `GET /api/v1/support/queue/assigned/` | Lista atribuições ativas |
| `GET /api/v1/support/queue/metrics/` | Métricas históricas |
| `POST /api/v1/support/queue/sync-novo/` | Sincronização manual |

### 8.4 Health Check Detalhado

```python
# GET /api/v1/support/queue/health/
{
    "timestamp": "2026-01-15T14:32:10Z",
    "summary": {
        "total_agents": 10,
        "online_agents": 5,
        "away_agents": 3,
        "eligible_agents": 4,
        "pending_queue_depth": 2,
        "system_ok": false,  # ← tickets pendentes
        "warnings": ["Apenas 1 agente elegível - regra 2 desativada"],
        "issues": ["2 ticket(s) aguardando na fila sem agente disponível"]
    },
    "absent_agents": [...],
    "eligible_agents": [...],
    "pending_tickets": [...],
    "last_assignments": [...]
}
```

### 8.5 Tarefas de Métricas (Celery Beat)

| Task | Schedule | Métricas Computadas |
|------|----------|---------------------|
| `task_aggregate_queue_metrics` | Diário 00:05 | avg/min/max/p50/p95 wait time |
| `task_aggregate_agent_metrics` | Diário 00:10 | total_chats, avg handle time |
| `task_poll_hubspot_agent_status` | A cada 3 min | Sync de disponibilidade |
| `task_sync_novo_stage_tickets` | Diário 08:00 | Backfill de tickets em NOVO |

---

## 9. Potenciais Melhorias

### 9.1 Ambiguidades Identificadas

1. **Prioridade de Tickets**: O sistema atual não considera prioridade do ticket (`HIGH`, `URGENT`) na ordenação da fila - apenas FIFO simples.

2. **Habilidades/Especialização**: Não há mapeamento de skills para roteamento especializado (ex: tickets técnicos para agentes técnicos).

3. **Timeouts na Fila**: Não há mecanismo automático de escalonamento para tickets muito antigos na fila.

### 9.2 Oportunidades de Melhoria

| Melhoria | Descrição | Impacto |
|----------|-----------|---------|
| **Priorização Inteligente** | Ordenar por `priority` + `entered_queue_at` | Tickets urgentes atendidos primeiro |
| **Roteamento por Skills** | Mapear `Agent.skills` × `Ticket.category` | Especialização eficiente |
| **Predição de Carga** | ML para prever tempo de resolução | Balanceamento proativo |
| **SLA Monitoring** | Alertas para tickets próximos de violar SLA | Conformidade operacional |
| **Self-Healing** | Auto-retry para tickets falhos | Menor intervenção manual |

---

## 10. Referências

### Arquivos Principais

```
apps/support/
├── auto_assign_service.py      # Orquestração principal
├── queue_service.py             # Algoritmo de seleção
├── tasks.py                     # Tarefas Celery
├── models.py                    # Entidades
├── api.py                       # Endpoints REST
├── schemas.py                   # Schemas Pydantic
├── migrations/0002_auto_assignment_tables.py
└── management/commands/check_assignment_system.py

apps/webhooks/handlers/
└── hubspot_handler.py           # Roteamento de webhooks

apps/integrations/hubspot/
└── client.py                    # Cliente HubSpot

docs/features/auto_assignment_system/
└── auto_assignment_system_comprehensive.md  # Este documento
```

### Constantes do Sistema

| Constante | Valor | Descrição |
|-----------|-------|-----------|
| `SUPPORT_PIPELINE_ID` | `636459134` | Pipeline de suporte HubSpot |
| `STAGE_NOVO_ID` | `939275049` | Estágio NOVO (novos tickets) |
| `STAGE_FECHADO_ID` | `939275052` | Estágio FECHADO (concluídos) |
| `HUBSPOT_TEAM_N1_ID` | `8` | Time N1 no HubSpot |
