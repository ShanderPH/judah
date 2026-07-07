# `apps.health` — Health Checks

## Resumo

Módulo simples com endpoints de health check para liveness e readiness, usados pelo Railway e por probes.

## Contexto

O Railway usa `/api/v1/health/` como liveness probe. O readiness probe `/api/v1/health/ready` verifica banco, cache, schema de auth e capacidade de emitir JWT.

> **Nota:** `apps.health` não está registrado em `INSTALLED_APPS` (`core/settings/base.py`). O router é montado diretamente em `core/urls.py`, então os endpoints respondem, mas o app não executa `AppConfig.ready()` nem sinais.

## Endpoints

Base: `/api/v1/health/`

| Método | Path | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/` | — | Liveness — sempre 200 se o processo estiver vivo |
| GET | `/ready` | — | Readiness — verifica DB, cache, schema e JWT mint |

## Liveness

Retorna:

```json
{
  "status": "alive",
  "timestamp": "2026-07-02T12:00:00+00:00",
  "version": "1.0.0"
}
```

## Readiness

Verifica:

1. Conexão com PostgreSQL (`SELECT 1`).
2. Redis (`set`/`get` de chave `health_ping`).
3. Tabelas `auth_users` e `token_blacklist_outstandingtoken` existem.
4. Consegue emitir um access token para um usuário existente.

Retorna 200 se tudo OK, 503 se degradado, com detalhes em `checks`.

## Arquivos relacionados

- [`apps/health/api.py`](../../apps/health/api.py)
- [`railway.toml`](../../railway.toml)
- [`common/logging.py`](../../common/logging.py) — suprime logs de health checks.

## Pontos de atenção

- O readiness testa JWT mint, que altera o banco de blacklist? Não — apenas cria um token na memória.
- Logs de health checks são suprimidos para evitar ruído.

## Recomendações

- Considerar verificação do broker Celery no readiness.
- Adicionar health check específico para Pinecone quando IA estiver habilitada.
