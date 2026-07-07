> [Índice completo](../INDEX.md)

# Monitoramento

## Resumo

Monitoramento do JUDAH envolve Sentry para erros, health checks para disponibilidade e métricas de negócio no app `analytics`.

## Health checks

| Endpoint | Descrição |
|----------|-----------|
| GET `/api/v1/health/` | Liveness probe — sempre 200 se o processo estiver vivo |
| GET `/api/v1/health/ready` | Readiness probe — verifica PostgreSQL, Redis, schema de auth e capacidade de emitir JWT |

> **Nota:** endpoints como `/health/db/`, `/health/redis/` e `/health/celery/` não existem no código atual. A verificação de dependências está concentrada em `/api/v1/health/ready`.

## Sentry

- Integrado via `sentry-sdk`.
- Captura exceções automaticamente.
- Performance tracing habilitado.

## Métricas de negócio

- Total de tickets abertos/resolvidos por dia.
- Tempo médio de resposta e resolução.
- Taxa de conformidade com SLA.
- Taxa de deflexão pela IA.
- Performance individual dos agentes.

## Alertas recomendados

- Taxa de erro > 1% por 5 minutos.
- Fila de tickets pendentes crescendo por mais de 15 minutos.
- Health check falhando.
- Consumo de tokens OpenAI acima do esperado.

## Arquivos relacionados

- [`services/health.md`](../services/health.md)
- [`services/analytics.md`](../services/analytics.md)
