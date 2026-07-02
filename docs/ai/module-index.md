> [Índice completo](../INDEX.md)

# Índice de Módulos

## Apps

| App | Responsabilidade | Arquivos principais |
|-----|------------------|---------------------|
| `auth_user` | Login, JWT, perfil | `api.py`, `services.py`, `models.py` |
| `church` | Igrejas, planos, gateways | `api.py`, `services.py`, `models.py` |
| `knowledge` | Artigos, chunks, sync, busca semântica | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `support` | Agentes, tickets, fila, atribuição, métricas | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `ai_agents` | Salomão, Heimdall, sessões, memórias, traces | `api.py`, `agents/`, `models.py` |
| `webhooks` | Recepção e processamento de webhooks | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `analytics` | Métricas, relatórios diários, performance | `api.py`, `services.py`, `tasks.py`, `models.py` |
| `integrations` | Clientes externos (HubSpot, Jira, etc.) | `clients/`, `services.py` |
| `health` | Health checks | `api.py`, `services.py` |
| `webapp` | Views Django legadas | `views.py`, `admin.py` |

## Módulos comuns

| Módulo | Responsabilidade |
|--------|------------------|
| `common.permissions` | Decorators de RBAC |
| `common.errors` | Exceções padronizadas |
| `common.pagination` | Paginação |
| `common.cache` | Helpers de cache Redis |

## Integrações externas

| Serviço | Cliente | Uso |
|---------|---------|-----|
| HubSpot | `integrations/hubspot/client.py` | Tickets, contatos, owners |
| Jira | `integrations/jira/client.py` | Issues, comentários |
| OpenAI | `ai_agents/llm.py` | Geração de respostas |
| Pinecone | `knowledge/vector_store.py` | Busca vetorial |

## Arquivos relacionados

- [`services/README.md`](../services/README.md)
- [`ai/codebase-map.md`](./codebase-map.md)
