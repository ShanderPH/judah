> [Índice completo](../INDEX.md)

# Logging

## Resumo

O JUDAH usa `structlog` para logging estruturado, com saída em JSON em produção.

## Configuração

```python
# core/settings/base.py
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
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
