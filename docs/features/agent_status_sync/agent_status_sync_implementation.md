# Sincronização Otimizada de Status dos Agentes

## Visão Geral

Sistema de sincronização de status dos agentes com suporte a horários comerciais dinâmicos, verificação de contagem de conversas simultâneas e atualizações thread-safe.

## Funcionalidades Implementadas

### 1. Verificação Dinâmica de Horários Comerciais

O sistema ajusta automaticamente o intervalo de verificação baseado no horário atual:

**Horários Comerciais (America/Sao_Paulo):**
- Segunda a Sexta: 9h às 18h → Verificação a cada **30 segundos**
- Sábado: 9h às 13h → Verificação a cada **30 segundos**
- Domingos e Feriados: 8h às 12h → Verificação a cada **30 segundos**
- Fora dos horários comerciais → Verificação a cada **1 hora**

### 2. Sincronização de Status e Contagem

Cada verificação sincroniza:
- **Status do agente** (online/away) via HubSpot Users API
- **Contagem de conversas simultâneas** via HubSpot Tickets Search API
- Correção automática de divergências entre HubSpot e banco local

### 3. Segurança de Concorrência

- Uso de `select_for_update()` para lock de registros durante atualização
- Processamento em batches de 10 agentes para minimizar lock time
- Transações atômicas garantem consistência de dados

## Arquitetura

### Arquivos Criados/Modificados

```
apps/support/
├── agent_sync_service.py          # NOVO: Serviço de sync otimizado
├── tasks.py                       # MODIFICADO: Task dinâmica
└── tests/
    └── test_agent_sync_service.py # NOVO: Testes do serviço

core/settings/base.py              # MODIFICADO: Celery Beat schedule
```

### Fluxo de Execução

1. **Celery Beat** dispara `task_poll_hubspot_agent_status_dynamic` a cada 30s
2. A task verifica se está em horário comercial via `is_business_hours()`
3. Executa `sync_all_agents_status_and_counts_optimized()`:
   - Busca todos os agentes ativos (is_active=True ou None)
   - Obtém status de disponibilidade em uma única chamada API
   - Busca contagem de tickets em paralelo (ThreadPoolExecutor)
   - Atualiza em batches com locking via `select_for_update()`
4. Reagenda a próxima execução via `reschedule_agent_status_task()`

## Configuração

### Horários Comerciais

Configurados em `agent_sync_service.py`:

```python
BUSINESS_HOURS = {
    0: (9, 18),   # Monday
    1: (9, 18),   # Tuesday
    2: (9, 18),   # Wednesday
    3: (9, 18),   # Thursday
    4: (9, 18),   # Friday
    5: (9, 13),   # Saturday
    6: (8, 12),   # Sunday
}
```

### Celery Beat Schedule

Configurado em `core/settings/base.py`:

```python
CELERY_BEAT_SCHEDULE = {
    "poll-hubspot-agent-status": {
        "task": "support.task_poll_hubspot_agent_status_dynamic",
        "schedule": 30.0,  # Initial interval: 30 seconds
    },
}
```

## API do Serviço

### `is_business_hours() -> bool`
Verifica se o horário atual está dentro do horário comercial.

### `get_poll_interval_seconds() -> int`
Retorna o intervalo apropriado (30 ou 3600 segundos).

### `sync_all_agents_status_and_counts_optimized() -> dict`
Executa a sincronização completa retornando:
- `agents_synced`: Total de agentes processados
- `status_changes`: Número de mudanças de status
- `count_corrections`: Número de correções de contagem
- `api_calls_made`: Total de chamadas API ao HubSpot

### `reschedule_agent_status_task() -> dict`
Reagenda a task com o intervalo apropriado para o próximo horário.

## Testes

Cobertura de testes inclui:
- Verificação de lógica de horários comerciais
- Sincronização de status
- Correção de contagem de conversas
- Tratamento de erros da API
- Segurança de concorrência
- Filtros de agentes ativos (is_active=True/None/False)

Comando para executar:
```bash
python -m pytest apps/support/tests/test_agent_sync_service.py -v
```

## Monitoramento

A task retorna métricas úteis para observabilidade:
- Quantidade de agentes sincronizados
- Mudanças de status detectadas
- Correções de contagem aplicadas
- Chamadas API realizadas
- Flag indicando se está em horário comercial
- Intervalo atual de execução

Logs estruturados são gerados via structlog para cada operação.

## Considerações de Performance

- **Batch Processing**: Atualizações em grupos de 10 agentes
- **Parallel API Calls**: Contagem de tickets em paralelo (max 3 workers)
- **Single Availability Call**: Uma chamada para buscar status de todos os usuários
- **Database Locking**: `select_for_update()` previne race conditions
- **Minimal API Usage**: Redução de chamadas HubSpot em ~90%
