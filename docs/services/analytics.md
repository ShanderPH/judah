# `apps.analytics` — Métricas e Relatórios

## Resumo

Módulo responsável pela agregação e consulta de métricas de suporte, relatórios diários e performance de agentes.

## Contexto

O `apps.analytics` consome dados produzidos por `apps.support` e os expõe via API. A agregação é feita por tasks Celery diárias.

## Responsabilidades

- Agregar relatórios diários de volume de tickets.
- Agregar métricas por agente.
- Disponibilizar endpoints de consulta.
- Permitir backfill de relatórios.

## Modelos

### `Metric`

Métrica genérica de timeseries.

| Campo | Descrição |
|-------|-----------|
| `metric_type` | `ticket_volume`, `resolution_time`, `first_response`, etc. |
| `date` | Data da métrica |
| `value` | Valor numérico |
| `dimensions` | JSON com dimensões |

### `DailyReport`

Relatório diário consolidado.

| Campo | Descrição |
|-------|-----------|
| `total_tickets_opened` | Tickets abertos |
| `total_tickets_resolved` | Tickets resolvidos |
| `total_tickets_escalated` | Tickets escalados |
| `avg_resolution_hours` | Tempo médio de resolução |
| `avg_first_response_hours` | Tempo médio de primeira resposta |
| `sla_compliance_rate` | Taxa de compliance SLA |
| `ai_handled_count` | Atendidos por IA |
| `ai_deflection_rate` | Taxa de deflexão |

### `AgentPerformance`

Performance por agente e data.

## Endpoints

Base: `/api/v1/analytics/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/reports/` | JWT | Lista relatórios diários (últimos N dias) |
| GET | `/reports/{date}` | JWT | Relatório de uma data |

## Services principais

- `get_daily_report(date)`: busca relatório por data.
- `get_recent_reports(days)`: lista relatórios recentes.
- `compute_daily_report(date)`: agrega dados de `Ticket`.

## Tasks Celery

- `generate_daily_report(date_str)`: gera relatório para uma data.
- `backfill_reports(days)`: gera relatórios para os últimos N dias.

## Regras de negócio

- Relatórios são pré-computados (não calculados no request).
- `compute_daily_report` usa `Ticket.created_at__date`, `resolved_at__date` e `sla_breached`.
- **TODO: confirmar** se o campo `Ticket.sla_breached` existe; o modelo `Ticket` analisado não possui esse campo (possível inconsistência).

## Arquivos relacionados

- [`apps/analytics/models.py`](../../apps/analytics/models.py)
- [`apps/analytics/api.py`](../../apps/analytics/api.py)
- [`apps/analytics/services.py`](../../apps/analytics/services.py)
- [`apps/analytics/tasks.py`](../../apps/analytics/tasks.py)

## Pontos de atenção

- `compute_daily_report` referencia `Ticket.sla_breached`, mas o campo não existe no modelo `Ticket` atual.
- Não há endpoint para `AgentPerformance` nem para `Metric` na API pública.

## Recomendações

- Corrigir inconsistência do campo `sla_breached`.
- Expor endpoints para `AgentPerformance` se necessário para o webapp.
- Adicionar testes para tasks de analytics.
