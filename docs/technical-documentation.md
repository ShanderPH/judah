# JUDAH — Documentação Técnica do Backend Unificado InChurch

> **Versão:** 1.0.0
> **Status:** Pre-production
> **Última atualização:** 2026-05-18

---

## 1. Visão Geral e Objetivo

### O Problema

A InChurch — plataforma SaaS de gestão de comunidades eclesiásticas — operava com **cinco sistemas legados desconexos**:

| Sistema Legado          | Função                                |
|-------------------------|---------------------------------------|
| Salomão v1              | Agente de IA de suporte (v1)          |
| Salomão WhatsApp        | Canal WhatsApp do agente              |
| Knowledge Base          | Base de conhecimento                  |
| Backoffice              | Painel administrativo                 |
| Helper CX               | Sistema de helpdesk / atendimento     |

Essa fragmentação gerava: duplicação de dados, inconsistência de métricas, dificuldade de manutenção, e impossibilidade de orquestrar agentes de IA com contexto unificado.

### A Solução: JUDAH

**JUDAH** é o backend unificado que consolida **suporte, base de conhecimento, analytics e agentes de IA** em um único serviço Django. Ele substitui todos os sistemas legados acima, oferecendo:

- **Pipeline de atendimento inteligente** com agente supervisor (Salomão) que orquestra triagem (Heimdall), busca semântica (RAG via Pinecone) e ações no HubSpot (via MCP).
- **Sistema de auto-atribuição** de tickets com algoritmo Matchmaker + SAT (Smart Agent Tracking) que monitora disponibilidade de agentes em tempo real.
- **Base de conhecimento sincronizada** com HubSpot CMS, indexada semanticamente para RAG.
- **Router unificado de webhooks** para HubSpot e Jira com verificação HMAC.
- **Analytics diário** de métricas de fila, performance de agentes e SLA.

### Valor Agregado para o Negócio

1. **Redução de tempo de resposta** — auto-atribuição em segundos vs. minutos/horas manuais.
2. **Escalabilidade do suporte** — agente de IA resolve dúvidas de plataforma sem intervenção humana.
3. **Visibilidade total** — métricas unificadas de performance de equipe e SLA.
4. **Manutenção simplificada** — uma codebase, um deploy, um ponto de observabilidade.

---

## 2. Arquitetura e Stack Tecnológica

### Stack Principal

| Camada              | Tecnologia                                        |
|---------------------|---------------------------------------------------|
| Runtime             | Python 3.14 (**versão exata obrigatória**)        |
| Framework Web       | Django 5.2 LTS + Django Ninja 1.6                 |
| Autenticação        | django-ninja-jwt (HS256)                          |
| Banco de Dados      | PostgreSQL 16 (Supabase)                          |
| Cache / Broker      | Redis 7                                           |
| Workers Assíncronos | Celery 5 + django-celery-beat                     |
| Runtime de IA       | Agno 2.5 (agents, teams, knowledge)               |
| Modelos de IA       | OpenAI (GPT-4o, GPT-4o-mini), Anthropic fallback  |
| Vector Store        | Pinecone serverless                               |
| Protocolo de Tools  | MCP 1.x (FastMCP server para HubSpot)             |
| Observabilidade     | structlog + Sentry + request IDs                  |
| Server              | Uvicorn (ASGI) / Gunicorn                         |
| Lint / Format       | Ruff (target py314)                               |
| Testes              | pytest + pytest-django + pytest-asyncio           |
| Deploy              | Railway (API, Celery Worker, Celery Beat)         |

### Frontend (WebApp)

| Camada              | Tecnologia                                        |
|---------------------|---------------------------------------------------|
| Framework           | Next.js 16 (App Router)                           |
| UI Library          | React 19                                          |
| Componentes         | HeroUI v3 + Tailwind CSS v4                       |
| Linguagem           | TypeScript (strict mode)                          |
| Animações           | GSAP 3                                            |
| Ícones              | Lucide React                                      |

### Princípios Arquiteturais

#### Clean Architecture (Adaptação Django)

O projeto segue os princípios de Clean Architecture adaptados ao ecossistema Django:

```
Camada de Apresentação (Controllers)   → Django Ninja Routers
Camada de Domínio (Use Cases)          → Services e Tasks Celery
Camada de Interfaces (Adapters)        → Clients de integrações externas
Camada de Repositórios (Data)          → Django Models + ORM
```

Cada Django app em `apps/` é um **módulo de domínio** autocontido com seus próprios models, services, schemas e tests.

#### Aderência SOLID

| Princípio          | Como é Aplicado                                                    |
|--------------------|--------------------------------------------------------------------|
| **S**RP            | Cada app Django tem responsabilidade única (support, knowledge, etc.) |
| **O**CP            | Agents estendem `BaseInChurchAgent` sem modificar a base            |
| **L**SP            | Sub-agentes (Heimdall, RAG, Action) substituíveis pelo Supervisor   |
| **I**SP            | Schemas Pydantic específicos por endpoint, sem `dict` genérico      |
| **D**IP            | Services dependem de interfaces (clients), não de implementações    |

---

## 3. Estrutura do Repositório

```
judah/
├── apps/                          # Módulos de domínio (Django apps)
│   ├── auth_user/                 # Modelo customizado de User com roles
│   ├── church/                    # Domínio de igrejas (clientes InChurch)
│   ├── knowledge/                 # Base de conhecimento + busca semântica
│   ├── support/                   # Tickets, filas, SAT, auto-atribuição
│   ├── ai_agents/                 # Agentes de IA (Salomão, Heimdall, RAG, Action)
│   │   ├── agents/                # Implementações dos agentes Agno
│   │   ├── api/                   # Routers Django Ninja para IA
│   │   ├── mcp_servers/           # FastMCP server para HubSpot
│   │   ├── services/              # Hidratação de dados, pricing
│   │   ├── tools/                 # MCP Tools (HubSpot, Knowledge)
│   │   └── utils/                 # Regras de negócio (timezone, holidays)
│   ├── integrations/              # Clients de sistemas externos
│   ├── webhooks/                  # Router canônico de webhooks inbound
│   ├── analytics/                 # Agregação diária de métricas
│   └── health/                    # Health checks
├── common/                        # Cross-cutting concerns
│   ├── circuit_breaker.py         # Circuit breaker process-local
│   ├── exceptions.py              # Hierarquia JudahError + handlers Ninja
│   ├── logging.py                 # Configuração structlog + correlation IDs
│   ├── middleware.py              # RequestLoggingMiddleware
│   ├── pagination.py              # Paginação padrão
│   ├── permissions.py             # Permissões customizadas
│   ├── rate_limit.py              # Rate limiter sliding-window (Redis)
│   └── utils.py                   # Utilitários gerais
├── core/                          # Configuração central do Django
│   ├── settings/                  # base / development / production / test
│   ├── urls.py                    # Root URLs + registro de routers Ninja
│   ├── celery.py                  # Factory do Celery app
│   ├── wsgi.py / asgi.py          # Entry points do servidor
├── webapp/                        # Frontend Next.js (monorepo)
├── hubspot-app/                   # App HubSpot (configuração de webhooks)
├── scripts/                       # Scripts utilitários e de teste
├── requirements/                  # Dependências Python (base, dev, test)
├── docker-compose.yml             # Stack local completa
├── Dockerfile*                    # Containers para Railway (API, worker, beat)
├── railway*.toml                  # Configurações de deploy Railway
├── Makefile                       # Comandos de desenvolvimento
├── pyproject.toml                 # Configuração Ruff, pytest, coverage
├── .pre-commit-config.yaml        # Hooks de pré-commit
├── .env.example                   # Template de variáveis de ambiente
├── conftest.py                    # Fixtures e configuração pytest
└── manage.py                      # Entry point Django
```

### Organização Interna de Cada Django App

```
app_name/
├── api.py              # Django Ninja Router (endpoints)
├── models.py           # Modelos Django (entidades de domínio)
├── schemas.py          # Pydantic schemas (request/response)
├── services.py         # Lógica de negócio (use cases)
├── tasks.py            # Celery tasks (background jobs)
├── admin.py            # Django Admin config
├── apps.py             # Django AppConfig
├── migrations/         # Migrations do banco
└── tests/              # Testes unitários e de integração
```

---

## 4. Integrações e Ferramentas

### Sistemas Externos

| Sistema              | Protocolo             | Uso no JUDAH                                              |
|----------------------|-----------------------|-----------------------------------------------------------|
| **HubSpot**          | REST API + Webhooks   | CRM, tickets de suporte, pipelines, base de conhecimento  |
| **Jira/Atlassian**   | REST API + Webhooks   | Criação e vinculação de issues técnicas                   |
| **Pinecone**         | gRPC/REST             | Vector store para RAG — busca semântica em artigos KB     |
| **Supabase**         | PostgreSQL + REST     | Hospedagem do banco de dados principal                    |
| **OpenAI**           | REST API              | Modelos GPT-4o e GPT-4o-mini para agentes de IA           |
| **Anthropic**        | REST API              | Modelo fallback para resiliência                          |
| **Sentry**           | SDK                   | Monitoramento de erros, traces e performance              |
| **n8n**              | Webhooks              | Automação de workflows externos                           |

### Fluxo de Dados Principal

```
HubSpot Webhook (ticket change)
  → Verificação HMAC (v1 ou v3)
  → Persiste WebhookEvent
  → Agenda Celery task
  → SalomaoSupervisorAgent.run_pipeline_async()
    → HeimdallTriageAgent classifica (gpt-4o-mini)
    → Rota definida:
      • DUVIDAS_PLATAFORMA → KnowledgeRagAgent (Pinecone RAG)
      • SUPORTE_TECNICO → HelpdeskActionAgent (MCP HubSpot tools)
      • ESCALAR_IMEDIATAMENTE → Handoff humano
    → Resposta formatada como SalomaoResponse
    → Tokens e custo persistidos em TokenTrackingLog
```

### Scheduled Tasks (Celery Beat)

| Task                              | Frequência           | Descrição                                     |
|-----------------------------------|----------------------|-----------------------------------------------|
| `sync-hubspot-team-members`       | Diário 06:00         | Sincroniza membros da equipe N1 do HubSpot    |
| `aggregate-queue-metrics`         | Diário 00:05         | Agrega métricas de fila                       |
| `sat-heartbeat`                   | A cada 20 segundos   | Sincroniza disponibilidade de agentes (SAT)   |
| `sat-reset-daily-counters`        | Diário 00:01         | Reseta contadores diários do SAT              |
| `matchmaker-drain-queue`          | A cada 60 segundos   | Processa fila de conversas pendentes          |
| `sync-novo-stage-tickets`         | Diário 08:00         | Sincroniza tickets do estágio NOVO            |
| `aggregate-agent-metrics`         | Diário 00:10         | Agrega métricas por agente                    |
| `reconcile-agent-counts`          | A cada hora (:30)    | Reconcilia contadores de chat com HubSpot     |

---

## 5. Padrões de Desenvolvimento e Regras Inegociáveis

### 5.1 Documentação de Código

> **É expressamente proibido o uso de comentários no código para documentar alterações ou lógicas de negócio.**

Toda a documentação técnica deve residir **obrigatoriamente** em arquivos Markdown específicos dentro da pasta `/docs/`.

**O que NÃO fazer:**

```python
# 2026-05-18 - Felipe: alterei a lógica de prioridade porque o cliente X reclamou
# Se o ticket for do tipo Y, usa a regra Z
def assign_ticket(ticket):
    ...
```

**O que fazer:**

```python
def assign_ticket(ticket):
    """Atribui ticket baseado na prioridade e disponibilidade do agente.

    Ver docs/support/ticket-assignment-rules.md para regras de negócio detalhadas.
    """
    ...
```

Docstrings Google-style são obrigatórias em módulos, classes e funções públicas — elas descrevem **o que** a função faz, não **por que** ou **histórico de alterações**.

### 5.2 Padrão de Versionamento

Todos os commits do projeto devem seguir rigorosamente a especificação do **Conventional Commits**:

```
<type>(<scope>): <subject>
```

| Type       | Uso                                              |
|------------|--------------------------------------------------|
| `feat`     | Nova funcionalidade                              |
| `fix`      | Correção de bug                                  |
| `refactor` | Refatoração sem mudança de comportamento         |
| `chore`    | Tarefas de manutenção (deps, config, CI)         |
| `docs`     | Alterações em documentação                       |
| `test`     | Adição ou correção de testes                     |
| `perf`     | Melhorias de performance                         |
| `hotfix`   | Correção urgente em produção                     |
| `spike`    | Investigação técnica / prova de conceito         |

**Exemplos:**

```
feat(support): add SAT heartbeat task for agent availability
fix(webhooks): handle missing HMAC header in Jira webhook
refactor(ai_agents): extract token extraction to helper method
chore(deps): bump agno from 2.4.0 to 2.5.0
docs(readme): update local setup instructions
```

Regras:

- Mensagem em **inglês**, voz imperativa
- Subject com no máximo **72 caracteres**
- Body opcional explicando o "porquê" da mudança

### 5.3 Testes e Qualidade

#### Cobertura de Testes

| Métrica                  | Valor Alvo      |
|--------------------------|-----------------|
| **Mínimo para deploy**   | 50%             |
| **Target ideal**         | 80%             |
| **Gate de aprovação**    | Entre 50% e 80% |

```toml
# pyproject.toml
[tool.coverage.report]
fail_under = 80
show_missing = true
```

Todo código crítico **exige testes automatizados**. Regras:

- **Services e use cases**: testes unitários obrigatórios
- **API endpoints**: testes de integração com `TestClient`
- **Models**: testes de constraints e regras de domínio
- **Celery tasks**: testes com `CELERY_TASK_ALWAYS_EAGER = True`
- **AI agents**: mocks para LLM calls (não chamar APIs reais em testes)

#### Comandos de Qualidade

```bash
make test          # pytest com coverage
make lint          # ruff check + format (com fixes)
make lint-check    # ruff check + format (modo CI, sem fixes)
```

#### Pre-commit Hooks

O projeto utiliza `pre-commit` com os seguintes hooks:

- Trailing whitespace fix
- End-of-file fixer
- YAML/TOML validation
- Large files check
- Merge conflict check
- Debug statements check
- Ruff lint (com auto-fix)
- Ruff format

---

## 6. Setup Local (Guia do Desenvolvedor)

### Pré-requisitos

| Dependência       | Versão       | Notas                                          |
|-------------------|--------------|------------------------------------------------|
| Python            | 3.14 (exata) | Instalar via pyenv ou instalador oficial       |
| PostgreSQL        | 16           | Ou usar projeto Supabase                       |
| Redis             | 7            | Broker, cache e session store                  |
| Docker + Compose  | Latest       | Opcional — para stack completa                 |

### Passo 1: Clone e Virtual Environment

```bash
git clone <repo-url>
cd judah
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### Passo 2: Instalar Dependências

```bash
make install
# Equivalente a:
# pip install -r requirements/dev.txt
# pre-commit install
```

### Passo 3: Configurar Variáveis de Ambiente

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais. Variáveis **obrigatórias** para desenvolvimento:

| Variável                  | Valor de Exemplo                                  |
|---------------------------|---------------------------------------------------|
| `DJANGO_SECRET_KEY`       | `dev-secret-key-change-me`                        |
| `DJANGO_DEBUG`            | `True`                                            |
| `DATABASE_URL`            | `postgresql://judah:judah_dev_password@localhost:5432/judah_dev` |
| `REDIS_URL`               | `redis://localhost:6379/0`                        |
| `OPENAI_API_KEY`          | `sk-...` (necessário para endpoints de IA)        |
| `HUBSPOT_ACCESS_TOKEN`    | Token do HubSpot (necessário para webhooks/MCP)   |
| `HUBSPOT_APP_SECRET`      | Secret para verificação HMAC                      |

### Passo 4: Migrate e Criar Superuser

```bash
make migrate
make superuser
```

### Passo 5: Rodar o Projeto

#### Opção A: Make (serviços externos rodando localmente)

```bash
# Terminal 1 — API
make run

# Terminal 2 — Celery Worker
make celery

# Terminal 3 — Celery Beat (scheduler)
make celery-beat
```

#### Opção B: Docker Compose (stack completa)

```bash
make docker-up
```

Isso sobe: API (porta 8000), PostgreSQL (5432), Redis (6379), Celery Worker e Celery Beat.

### Passo 6: Verificar

```bash
# API docs (OpenAPI/Swagger)
open http://localhost:8000/api/v1/docs

# Django Admin
open http://localhost:8000/admin/
```

### Executando a Suíte de Testes

```bash
# Todos os testes com coverage
make test

# Tests de um app específico
pytest apps/support/tests/

# Pular testes lentos
pytest -m "not slow"

# Tests em paralelo (se pytest-xdist instalado)
pytest -n auto
```

> **Atenção:** O `conftest.py` deleta dados das tabelas de suporte antes de cada teste. **Nunca** aponte `DATABASE_URL` para produção ao rodar testes.

### Estrutura de Settings por Ambiente

| Arquivo                    | Uso                                          |
|----------------------------|----------------------------------------------|
| `core/settings/base.py`    | Configurações compartilhadas                 |
| `core/settings/development.py` | Desenvolvimento local (debug, toolbar)   |
| `core/settings/production.py`  | Produção (Railway, Sentry, JSON logs)    |
| `core/settings/test.py`        | Testes (SQLite, task eager)              |

---

## 7. AI Agent Architecture (Resumo)

### Salomão — Supervisor Multi-Agente

```
POST /api/v1/ai/salomao/chat (JWT-authenticated)
  → SalomaoSupervisorAgent.run_pipeline_async()
    1. Circuit breaker: rejeita se sessão > 15k tokens
    2. Greeting injection: primeira mensagem com saudação obrigatória
    3. Team.run(message) — Agno coordena:
       a. HeimdallTriageAgent (gpt-4o-mini) → classifica mensagem
       b. Baseado na rota:
          • DUVIDAS_PLATAFORMA/ATENDIMENTO_IA → KnowledgeRagAgent (Pinecone RAG)
          • BOLETO/FINANCEIRO/SUPORTE → HelpdeskActionAgent (MCP HubSpot tools)
          • ESCALAR_IMEDIATAMENTE → handoff humano
    4. Token tracking: persiste custo em TokenTrackingLog
```

### Sessões

Persistidas em Redis sob `inchurch:agent:{session_id}`:

- `user-{user.pk}` para chat autenticado
- `hubspot-ticket-{ticket_id}` para webhooks

---

## 8. Deploy (Railway)

| Container           | Dockerfile            | Função                          |
|---------------------|-----------------------|---------------------------------|
| API                 | `Dockerfile`          | Uvicorn + Django Ninja          |
| Celery Worker       | `Dockerfile.worker`   | Processa tasks assíncronas      |
| Celery Beat         | `Dockerfile.beat`     | Scheduler de tasks periódicas   |

Railway termina TLS na edge. Django confia em `X-Forwarded-Proto`. Não ativar `SECURE_SSL_REDIRECT` (quebra health check interno).

---

## 9. Checklist Pré-Deploy

Antes de promover para produção:

- [ ] Migrations aplicadas em staging com sucesso
- [ ] `make lint-check` passa sem erros
- [ ] `make test` passa com coverage >= 50%
- [ ] `HUBSPOT_APP_SECRET` configurado (não vazio)
- [ ] `debug_mode=False` em todos os agentes de IA
- [ ] Sentry sem novos erros após 5min em staging
- [ ] Feature flags configuradas (`AI_ROUTING_ENABLED`)
- [ ] Plano de rollback documentado
- [ ] Janela de deploy comunicada ao time
