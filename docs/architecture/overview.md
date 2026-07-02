# Visão Geral da Arquitetura

## Resumo

O JUDAH é o backend unificado da InChurch, uma plataforma SaaS de gestão de comunidades eclesiásticas. Ele consolida cinco sistemas legados (Salomão v1, Salomão WhatsApp, Knowledge Base, Backoffice e Helper CX) em um único serviço Django que orquestra atendimento, base de conhecimento, analytics e agentes de IA.

## Contexto

A arquitetura segue uma adaptação de Clean Architecture ao ecossistema Django:

- **Camada de Apresentação:** Django Ninja routers (`apps/<app>/api.py`).
- **Camada de Domínio:** services, tasks Celery e regras de negócio (`apps/<app>/services.py`, `tasks.py`).
- **Camada de Interfaces/Adapters:** clients de integrações externas (`apps/integrations/`).
- **Camada de Repositórios:** Django Models + ORM (`apps/<app>/models.py`).

## Stack tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Runtime | Python 3.14 (versão exata obrigatória) |
| Framework web | Django 5.2 LTS + Django Ninja 1.6 |
| Autenticação | django-ninja-jwt (HS256) |
| Banco de dados | PostgreSQL 16 (Supabase) |
| Cache / broker | Redis 7 |
| Workers | Celery 5 + django-celery-beat |
| Runtime de IA | Agno 2.5 |
| Modelos LLM | OpenAI GPT-4o / GPT-4o-mini, Anthropic fallback |
| Vector store | Pinecone serverless |
| Ferramentas externas | MCP 1.x (FastMCP) |
| Frontend | Next.js 16 + React 19 + HeroUI v3 + Tailwind CSS v4 |
| Observabilidade | structlog + Sentry + request IDs |
| Deploy | Railway (API, Worker, Beat) |
| Lint / testes | Ruff (target py314), pytest, pytest-django, pytest-asyncio |

## Princípios arquiteturais

1. **Um app por domínio:** cada app Django em `apps/` tem responsabilidade única e bem definida.
2. **Schemas explícitos:** request/response são tipados com Pydantic v2; nenhum `dict` solto na API.
3. **Lógica fora das views:** views chamam services; services encapsulam regras de negócio.
4. **Tarefas assíncronas:** operações lentas ou externas são delegadas ao Celery.
5. **Feature flags:** funcionalidades sensíveis (como o roteamento de IA) são controladas por flags (`AI_ROUTING_ENABLED`).
6. **Observabilidade embutida:** todos os requests carregam `request_id`; logs são estruturados.

## Visão de alto nível

```text
HubSpot ──► /api/v1/webhooks/hubspot/ ──► WebhookEvent ──► Celery task
                                              │
                                              ▼
                                    Matchmaker / Auto-assign
                                              │
                                              ▼
                                    Agent (HubSpot owner)

Usuário autenticado ──► /api/v1/ai/salomao/chat ──► SalomaoSupervisorAgent
                                                          │
                    ┌─────────────────────────────────────┼─────────────────────────────────────┐
                    ▼                                     ▼                                     ▼
         HeimdallTriageAgent                 KnowledgeRagAgent                      HelpdeskActionAgent
         (gpt-4o-mini, output_schema)        (Pinecone RAG)                       (MCP tools)
                                                                                         │
                                                                                         ▼
                                                                               HubSpot MCP server
```

## Arquivos relacionados

- [`core/urls.py`](../../core/urls.py): registro dos routers Ninja e feature flag de IA.
- [`core/settings/base.py`](../../core/settings/base.py): configurações compartilhadas, Celery Beat, CORS, JWT.
- [`core/celery.py`](../../core/celery.py): fábrica do app Celery.
- [`docker-compose.yml`](../../docker-compose.yml): stack local completa.
- [`pyproject.toml`](../../pyproject.toml): Ruff, pytest, coverage.

## Pontos de atenção

- O roteamento de IA está **desabilitado por padrão** (`AI_ROUTING_ENABLED=false`).
- Python 3.14 é exigido; outras versões não são suportadas.
- O projeto usa Supabase/PostgreSQL; SQLite não é o target de produção.

## Recomendações

- Manter a separação de responsabilidades ao criar novos apps.
- Novas integrações externas devem viver em `apps/integrations/<nome>/`.
- Novos agentes devem estender `BaseInChurchAgent` em `apps/ai_agents/agents/`.
