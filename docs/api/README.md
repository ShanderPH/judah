# API

## Resumo

A API do JUDAH é RESTful, construída com Django Ninja, versionada em `/api/v1/` e documentada automaticamente via OpenAPI/Swagger.

## Contexto

A API é organizada em routers por domínio. A autenticação é baseada em JWT (HS256). Alguns endpoints (webhooks, health, knowledge search) são públicos por necessidade.

## Base URL

```text
/api/v1/
```

## Documentação interativa

```text
/api/v1/docs
```

## Routers

| Router | Prefixo | Auth | Tags |
|--------|---------|------|------|
| Auth | `/auth/` | Parcial | Auth |
| Church | `/church/` | JWT | Church |
| Knowledge | `/knowledge/` | Parcial | Knowledge |
| Support | `/support/` | JWT | Support |
| Webhooks | `/webhooks/` | — | Webhooks |
| Analytics | `/analytics/` | JWT | Analytics |
| Health | `/health/` | — | Health |
| AI Agents | `/ai/` | Parcial | AI Agents (condicional) |

## Arquivos relacionados

- [`api/endpoints.md`](./endpoints.md): lista completa de endpoints.
- [`api/authentication.md`](./authentication.md): como autenticar.
- [`api/examples.md`](./examples.md): exemplos de requisições.
- [`core/urls.py`](../../core/urls.py): registro dos routers.
