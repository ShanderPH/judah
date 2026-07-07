> [Índice completo](../INDEX.md)

# Índice de Módulos

## Apps

| App | Responsabilidade | Arquivos principais |
|-----|------------------|---------------------|
| `auth_user` | Login, JWT, perfil | `api.py`, `services.py`, `models.py` |
| `church` | Igrejas, planos, gateways | `api.py`, `services.py`, `models.py` |
| `knowledge` | Artigos, chunks, sync, busca semântica | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `support` | Agentes, tickets, fila, atribuição, métricas | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `ai_agents` | Salomão, Heimdall, sessões, memórias, traces | `api.py`, `agents/`, `contracts.py`, `models.py` |
| `webhooks` | Recepção e processamento de webhooks | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `analytics` | Métricas, relatórios diários, performance | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `integrations` | Clientes externos (HubSpot, Jira, etc.) | `clients/`, `services.py` |
| `health` | Health checks (router-only, não registrado em `INSTALLED_APPS`) | `api.py` |
| `webapp` | Frontend Next.js 16 (fora de `apps/`) | `webapp/` |

## Módulos comuns

| Módulo | Responsabilidade |
|--------|------------------|
| `common.permissions` | Decorators de RBAC |
| `common.exceptions` | Exceções padronizadas (`JudahError` + handlers Ninja) |
| `common.pagination` | Paginação |
| `common.cache` | Helpers de cache Redis |
| `common.logging` | Configuração do structlog |
| `common.middleware` | RequestLoggingMiddleware |
| `common.rate_limit` | Rate limiter sliding-window |
| `common.circuit_breaker` | Circuit breaker process-local |
| `common.utils` | Utilitários diversos |

## Integrações externas

| Serviço | Cliente | Uso |
|---------|---------|-----|
| HubSpot | `apps/integrations/hubspot/client.py` | Tickets, contatos, owners |
| Jira | `apps/integrations/jira/client.py` | Issues, comentários |
| Supabase | `apps/integrations/supabase_client/client.py` | Cliente Supabase (uso limitado) |
| Pinecone | `apps/integrations/pinecone_client/client.py` | Busca vetorial |
| OpenAI | `apps/ai_agents/agents/base.py` (via Agno) | Geração de respostas |

## Arquivos relacionados

- [`services/README.md`](../services/README.md)
- [`ai/codebase-map.md`](./codebase-map.md)
