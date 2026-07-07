> [Índice completo](../INDEX.md)

# Mapa do Código

## Estrutura de diretórios

```text
judah/
├── apps/                    # Django apps
│   ├── auth_user/           # autenticação e usuários
│   ├── church/              # igrejas, planos, gateways
│   ├── knowledge/           # base de conhecimento
│   ├── support/             # atendimento e fila
│   ├── ai_agents/           # agentes de IA
│   ├── webhooks/            # webhooks HubSpot/Jira
│   ├── analytics/           # métricas e relatórios
│   ├── integrations/        # integrações externas
│   └── health/              # health checks (router-only, não está em INSTALLED_APPS)
├── common/                  # utilitários, permissões, exceções, logging
├── core/                    # settings, urls, wsgi, asgi, celery app
├── docs/                    # documentação
├── requirements/            # dependências Python
├── webapp/                  # frontend Next.js 16 + React 19 + Tailwind 4
├── manage.py
├── Makefile
├── run.ps1
├── run_checks.py
├── run_tests_local.py
├── Dockerfile
├── Dockerfile.worker
├── Dockerfile.beat
├── railway.toml
├── railway.worker.toml
└── railway.beat.toml
```

## Arquivos-chave

| Arquivo | Propósito |
|---------|-----------|
| `core/settings/base.py` | Configurações base |
| `core/settings/production.py` | Overrides de produção |
| `core/settings/development.py` | Overrides de desenvolvimento |
| `core/settings/test.py` | Settings de teste |
| `core/settings/__init__.py` | Seleção de settings por `DJANGO_ENV` |
| `core/urls.py` | Registro de routers Ninja |
| `core/celery.py` | Configuração do Celery |
| `apps/support/services.py` | CRUD de tickets |
| `apps/support/queue_service.py` | Seleção de agentes para atribuição |
| `apps/support/matchmaker_service.py` | Matchmaker de fila |
| `apps/support/auto_assign_service.py` | Auto-atribuição de tickets |
| `apps/ai_agents/agents/supervisor.py` | Supervisor Salomão (Team Agno) |
| `apps/ai_agents/agents/triage.py` | Heimdall (triagem) |
| `apps/ai_agents/agents/rag.py` | KnowledgeRagAgent |
| `apps/ai_agents/agents/action.py` | HelpdeskActionAgent |
| `apps/ai_agents/agents/salomao_chat.py` | Adapter Salomão v1 |
| `apps/ai_agents/contracts.py` | Contratos Pydantic para handoffs entre agentes |
| `apps/webhooks/services.py` | Persistência e roteamento de webhooks |
| `common/exceptions.py` | Exceções padronizadas |
| `common/permissions.py` | RBAC |

## Convenções

- Cada app tem `models.py`, `api.py`, `schemas.py`, `services.py`, `tasks.py` (quando aplicável).
- `schemas.py` define contratos de API (Pydantic v2).
- Testes ficam em `apps/<app>/tests/`.

## Arquivos relacionados

- [`ai/module-index.md`](./module-index.md)
