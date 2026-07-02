# Módulos e Apps

## Resumo

O repositório é organizado como um monorepo contendo o backend Django, o frontend Next.js e a configuração de infraestrutura. Este documento descreve os módulos (Django apps) do backend e os cross-cutting concerns em `common/` e `core/`.

## Contexto

Cada app Django em `apps/` representa um domínio de negócio autocontido, com seus próprios models, services, schemas e tests. Apps não devem circular dependências: `common/` e `core/` são dependidos por todos, mas apps de domínio preferem depender de `apps.integrations` e de contratos internos.

## Estrutura do repositório

```text
judah/
├── apps/                    # Domínios do Django
│   ├── auth_user/
│   ├── church/
│   ├── knowledge/
│   ├── support/
│   ├── ai_agents/
│   ├── integrations/
│   ├── webhooks/
│   ├── analytics/
│   └── health/
├── common/                  # Cross-cutting concerns
├── core/                    # Configuração central do Django
├── webapp/                  # Frontend Next.js
├── hubspot-app/             # Configuração de webhooks HubSpot
├── scripts/                 # Scripts utilitários
├── requirements/            # Dependências Python
├── docker-compose.yml
├── Dockerfile*              # API, worker, beat
└── railway*.toml
```

## Apps de domínio

### `apps.auth_user`

- **Responsabilidade:** autenticação, usuários customizados e papéis.
- **Modelo principal:** `User` (tabela `auth_users`), com roles `admin`, `manager`, `agent`, `viewer`.
- **Endpoints:** `/api/v1/auth/*` (login, refresh, logout, register, me, change-password).
- **Arquivos chave:** [`apps/auth_user/models.py`](../../apps/auth_user/models.py), [`apps/auth_user/api.py`](../../apps/auth_user/api.py), [`apps/auth_user/services.py`](../../apps/auth_user/services.py).

### `apps.church`

- **Responsabilidade:** domínio de igrejas clientes da InChurch.
- **Modelos:** `Church`, `Plan`, `Gateway`.
- **Endpoints:** `/api/v1/church/*` (listar, detalhe).
- **Arquivos chave:** [`apps/church/models.py`](../../apps/church/models.py), [`apps/church/api.py`](../../apps/church/api.py).

### `apps.knowledge`

- **Responsabilidade:** base de conhecimento sincronizada com HubSpot CMS.
- **Modelos:** `Category`, `Article`, `ArticleChunk`, `KBSyncLog`.
- **Endpoints:** `/api/v1/knowledge/*` (artigos, busca semântica).
- **Arquivos chave:** [`apps/knowledge/models.py`](../../apps/knowledge/models.py), [`apps/knowledge/services.py`](../../apps/knowledge/services.py).

### `apps.support`

- **Responsabilidade:** tickets, filas, auto-atribuição, SAT, Matchmaker e métricas de fila.
- **Modelos principais:** `Ticket`, `Agent`, `NewConversation`, `AssignedConversation`, `ClosedConversation`, `AssignmentLog`, `QueuePerformanceMetrics`, `AgentMetrics`, `AgentDailyTimeLog`, `BusinessHoursConfig`, `SpecialSchedule`.
- **Endpoints:** `/api/v1/support/*`.
- **Services/Tasks:** `auto_assign_service.py`, `matchmaker_service.py`, `sat_service.py`, `queue_service.py`, `agent_sync_service.py`, `tasks.py`.
- **Arquivos chave:** [`apps/support/models.py`](../../apps/support/models.py), [`apps/support/api.py`](../../apps/support/api.py), [`apps/support/tasks.py`](../../apps/support/tasks.py).

### `apps.ai_agents`

- **Responsabilidade:** orquestração de agentes de IA (Salomão, Heimdall, RAG, Action).
- **Modelos:** `AgentSession`, `AgentMemory`, `AgentTrace`, `TokenTrackingLog`.
- **Endpoints:** `/api/v1/ai/*` (habilitado apenas com `AI_ROUTING_ENABLED=true`).
- **Agentes:** `HeimdallTriageAgent`, `KnowledgeRagAgent`, `HelpdeskActionAgent`, `SalomaoSupervisorAgent`.
- **Arquivos chave:** [`apps/ai_agents/agents/supervisor.py`](../../apps/ai_agents/agents/supervisor.py), [`apps/ai_agents/api/webhooks.py`](../../apps/ai_agents/api/webhooks.py), [`apps/ai_agents/mcp_servers/hubspot_server.py`](../../apps/ai_agents/mcp_servers/hubspot_server.py).

### `apps.integrations`

- **Responsabilidade:** clients tipados para sistemas externos.
- **Submódulos:** `hubspot/`, `jira/`, `pinecone_client/`, `supabase_client/`.
- **Arquivos chave:** [`apps/integrations/hubspot/client.py`](../../apps/integrations/hubspot/client.py), [`apps/integrations/jira/client.py`](../../apps/integrations/jira/client.py).

### `apps.webhooks`

- **Responsabilidade:** receber, validar assinatura, persistir e rotear webhooks inbound.
- **Modelos:** `WebhookEvent`, `DeadLetterQueue`.
- **Endpoints:** `/api/v1/webhooks/hubspot/`, `/api/v1/webhooks/jira/`.
- **Handlers:** `hubspot_handler.py`, `jira_handler.py`.
- **Arquivos chave:** [`apps/webhooks/api.py`](../../apps/webhooks/api.py), [`apps/webhooks/services.py`](../../apps/webhooks/services.py).

### `apps.analytics`

- **Responsabilidade:** agregação e consulta de métricas de suporte.
- **Modelos:** `Metric`, `DailyReport`, `AgentPerformance`.
- **Endpoints:** `/api/v1/analytics/*`.
- **Tasks:** `generate_daily_report`, `backfill_reports`.
- **Arquivos chave:** [`apps/analytics/models.py`](../../apps/analytics/models.py), [`apps/analytics/tasks.py`](../../apps/analytics/tasks.py).

### `apps.health`

- **Responsabilidade:** health checks para Railway e probes.
- **Endpoints:** `/api/v1/health/` (liveness), `/api/v1/health/ready` (readiness).
- **Arquivos chave:** [`apps/health/api.py`](../../apps/health/api.py).

## Cross-cutting concerns (`common/`)

| Módulo | Responsabilidade | Arquivo |
|--------|------------------|---------|
| Exceções | Hierarquia `JudahError` e handlers Ninja | [`common/exceptions.py`](../../common/exceptions.py) |
| Logging | structlog, correlation IDs, filtros | [`common/logging.py`](../../common/logging.py) |
| Middleware | `RequestLoggingMiddleware` (request_id, duracao) | [`common/middleware.py`](../../common/middleware.py) |
| Rate limit | Sliding window por usuário/IP (Redis) | [`common/rate_limit.py`](../../common/rate_limit.py) |
| Circuit breaker | Proteção local para chamadas externas | [`common/circuit_breaker.py`](../../common/circuit_breaker.py) |
| Permissões | Helpers `require_role`, `require_admin`, etc. | [`common/permissions.py`](../../common/permissions.py) |
| Paginação | `StandardPagination`, `StandardCursorPagination` | [`common/pagination.py`](../../common/pagination.py) |
| Cache | Decorador `cached`, invalidação por prefixo | [`common/cache.py`](../../common/cache.py) |
| Utilitários | UUID, slugify, truncate, máscara de secrets | [`common/utils.py`](../../common/utils.py) |

## Configuração central (`core/`)

| Módulo | Responsabilidade | Arquivo |
|--------|------------------|---------|
| Settings | `base`, `development`, `production`, `test` | [`core/settings/`](../../core/settings/) |
| URLs | Registro de routers Ninja | [`core/urls.py`](../../core/urls.py) |
| Celery | App factory e startup task | [`core/celery.py`](../../core/celery.py) |
| ASGI/WSGI | Entry points do servidor | [`core/asgi.py`](../../core/asgi.py), [`core/wsgi.py`](../../core/wsgi.py) |

## Relações entre módulos

```text
webapp ──► auth_user (JWT)
webapp ──► support / analytics / health (via proxy backend)

webhooks ──► support (tasks de auto-atribuição)
webhooks ──► ai_agents (quando AI_ROUTING_ENABLED=true)

ai_agents ──► integrations (HubSpot, Jira, Pinecone)
ai_agents ──► knowledge (RAG)

support ──► integrations (HubSpot)
support ──► analytics (métricas)

analytics ──► support (Ticket, ClosedConversation)
```

## Pontos de atenção

- `apps.support` é o maior e mais complexo; depende de `apps.integrations`.
- `apps.ai_agents` importa `apps.integrations` e `apps.knowledge`.
- `apps.webhooks` importa handlers de `support` e `ai_agents`.
- Não há dependência cíclica evidente, mas `support` e `webhooks` são fortemente acoplados.

## Recomendações

- Considerar um diagrama de dependências automático (ex: `pyreverse` ou `import-linter`).
- Manter `common/` e `core/` livres de regras de negócio.
- Novos domínios devem seguir o padrão de `models.py`, `schemas.py`, `services.py`, `api.py`, `tasks.py`, `tests/`.
