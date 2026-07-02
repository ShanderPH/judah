> [Índice completo](../INDEX.md)

# Monitoramento

## Resumo

Monitoramento do JUDAH envolve Sentry para erros, health checks para disponibilidade e métricas de negócio no app `analytics`.

## Health checks

| Endpoint | Descrição |
|----------|-----------|
| GET `/health/` | Retorna status geral do sistema |
| GET `/health/db/` | Verifica conexão com PostgreSQL |
| GET `/health/redis/` | Verifica conexão com Redis |
| GET `/health/celery/` | Verifica broker Celery |

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
