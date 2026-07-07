> [Índice completo](../INDEX.md)

# Logging

## Resumo

O JUDAH usa `structlog` para logging estruturado, com saída em JSON em produção.

## Configuração

A configuração completa está em [`core/settings/base.py`](../../core/settings/base.py). O resumo:

- Logs são formatados via `structlog.stdlib.ProcessorFormatter`.
- Em produção (`DJANGO_ENV=production`) o renderer é `JSONRenderer`.
- Em desenvolvimento o renderer é `ConsoleRenderer` com cores.
- A chain `_STRUCTLOG_PRE_CHAIN` adiciona `request_id`, nível, nome do logger e timestamp ISO a todos os registros.

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.ExceptionRenderer(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
```

## Níveis

- `DEBUG` — apenas local.
- `INFO` — eventos de negócio (atribuição, fechamento, sync).
- `WARNING` — eventos esperados mas não ideais (retry, fallback).
- `ERROR` — falhas que precisam de atenção.
- `CRITICAL` — falhas graves (DB indisponível).

## Campos padrão

```json
{
  "event": "ticket_assigned",
  "level": "info",
  "logger": "support.services",
  "timestamp": "2026-07-02T10:00:00Z",
  "ticket_id": "123",
  "agent_id": "uuid",
  "assignment_type": "automatic"
}
```

## Rastreamento

- `request_id` propagado via contexto.
- `session_id` para conversas de IA.
- `ticket_id` para eventos de suporte.

## Arquivos relacionados

- [`setup/environment-variables.md`](../setup/environment-variables.md)
