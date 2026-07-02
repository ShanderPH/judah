# Índice da Documentação JUDAH

## Raiz

- [`README.md`](./README.md) — Como navegar nesta documentação.
- [`INDEX.md`](./INDEX.md) — Este arquivo.
- [`REPORT.md`](./REPORT.md) — Relatório de entrega da documentação.

## Arquitetura

- [`architecture/overview.md`](./architecture/overview.md) — Visão geral do sistema, stack e princípios arquiteturais.
- [`architecture/system-context.md`](./architecture/system-context.md) — Contexto externo: integrações, atores e fronteiras.
- [`architecture/modules.md`](./architecture/modules.md) — Módulos e apps do Django, responsabilidades e relações.
- [`architecture/data-flow.md`](./architecture/data-flow.md) — Fluxos de dados principais (webhook, chat, atribuição, analytics).
- [`architecture/decisions.md`](./architecture/decisions.md) — Decisões técnicas registradas (ADRs).

## Setup

- [`setup/local-development.md`](./setup/local-development.md) — Como rodar o projeto localmente.
- [`setup/environment-variables.md`](./setup/environment-variables.md) — Variáveis de ambiente obrigatórias e opcionais.
- [`setup/docker.md`](./setup/docker.md) — Como subir a stack com Docker Compose.
- [`setup/troubleshooting.md`](./setup/troubleshooting.md) — Problemas comuns e soluções.

## Negócio

- [`business/business-rules.md`](./business/business-rules.md) — Regras de negócio explícitas e implícitas.
- [`business/domain-glossary.md`](./business/domain-glossary.md) — Glossário de termos do domínio.
- [`business/workflows.md`](./business/workflows.md) — Fluxos de negócio principais.

## Serviços

- [`services/README.md`](./services/README.md) — Índice dos serviços e módulos.
- [`services/auth_user.md`](./services/auth_user.md) — Autenticação e usuários.
- [`services/church.md`](./services/church.md) — Igrejas e planos.
- [`services/knowledge.md`](./services/knowledge.md) — Base de conhecimento.
- [`services/support.md`](./services/support.md) — Tickets, filas, SAT, Matchmaker e auto-atribuição.
- [`services/ai_agents.md`](./services/ai_agents.md) — Agentes de IA (Salomão, Heimdall, RAG, Action, MCP).
- [`services/integrations.md`](./services/integrations.md) — Integrações externas (HubSpot, Jira, Pinecone, Supabase).
- [`services/webhooks.md`](./services/webhooks.md) — Recebimento e roteamento de webhooks.
- [`services/analytics.md`](./services/analytics.md) — Métricas e relatórios.
- [`services/health.md`](./services/health.md) — Health checks.
- [`services/webapp.md`](./services/webapp.md) — Frontend Next.js (visão geral).

## API

- [`api/README.md`](./api/README.md) — Visão geral da API.
- [`api/endpoints.md`](./api/endpoints.md) — Endpoints HTTP por router.
- [`api/authentication.md`](./api/authentication.md) — Autenticação e autorização.
- [`api/examples.md`](./api/examples.md) — Exemplos de requisições e respostas.

## Banco de Dados

- [`database/overview.md`](./database/overview.md) — Visão geral da persistência.
- [`database/models.md`](./database/models.md) — Modelos por app.
- [`database/migrations.md`](./database/migrations.md) — Estratégia de migrations.
- [`database/relationships.md`](./database/relationships.md) — Relacionamentos entre entidades.

## Contribuição

- [`contributing/README.md`](./contributing/README.md) — Guia do contribuidor.
- [`contributing/code-style.md`](./contributing/code-style.md) — Estilo de código (Ruff, MyPy, TypeScript).
- [`contributing/commit-conventions.md`](./contributing/commit-conventions.md) — Conventional Commits.
- [`contributing/PR-checklist.md`](./contributing/PR-checklist.md) — Checklist antes de abrir PR.
- [`contributing/testing-guide.md`](./contributing/testing-guide.md) — Como escrever e executar testes.

## Operações

- [`operations/deployment.md`](./operations/deployment.md) — Deploy no Railway.
- [`operations/monitoring.md`](./operations/monitoring.md) — Observabilidade e métricas.
- [`operations/logging.md`](./operations/logging.md) — Estratégia de logs com structlog.
- [`operations/rollback.md`](./operations/rollback.md) — Rollback e plano de contingência.

## Segurança

- [`security/overview.md`](./security/overview.md) — Visão geral de segurança.
- [`security/risks.md`](./security/risks.md) — Riscos identificados.
- [`security/recommendations.md`](./security/recommendations.md) — Recomendações de hardening.

## Inteligência Artificial

- [`ai/ai-context.md`](./ai/ai-context.md) — Resumo otimizado para agentes de IA.
- [`ai/codebase-map.md`](./ai/codebase-map.md) — Mapa rápido da codebase.
- [`ai/module-index.md`](./ai/module-index.md) — Índice de módulos para RAG.
- [`ai/maintenance-notes.md`](./ai/maintenance-notes.md) — Notas de manutenção para IAs.
