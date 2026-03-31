# JUDAH — Plano de Unificação de Backends InChurch

## 1. Inventário dos Backends Atuais

### 1.1 Salomão v1 (`salomao-v1-production`)
**Stack:** FastAPI + OpenAI + Pinecone + Supabase
**Responsabilidades:**
- Agente RAG de suporte ao cliente (chatbot IA)
- Busca semântica em base de conhecimento via Pinecone embeddings
- Endpoint `/api/v1/chat/message` — recebe mensagens, busca contexto em Pinecone, enriquece com artigos do Supabase e gera resposta com GPT-4o-mini
- Endpoint `/api/v1/articles/search?q=` — busca semântica de artigos
- Threshold de relevância (score > 0.7), agregação por artigo, conversation memory

**Problemas identificados:**
- Acoplado a um único modelo LLM (GPT-4o-mini hardcoded)
- Sem observabilidade ou tracing de agente
- Sem guardrails ou fallback estruturado
- Conversation memory não persistente entre sessões

---

### 1.2 Salomão WhatsApp (`salomao-whatsapp-production`)
**Stack:** FastAPI + HubSpot API + Webhooks
**Responsabilidades:**
- Bot para canal WhatsApp integrado ao HubSpot
- Recebe webhooks `conversation.newMessage` do HubSpot
- Busca ticket associado via `hs_conversations_originating_thread_id`
- Filtra por pipeline e estágio específico antes de processar
- Busca mensagens do thread e envia para processamento IA
- Coleta de dados (CNPJ, telefone) via conversa automatizada

**Problemas identificados:**
- Webhook genérico processa TODAS as mensagens de TODAS as pipelines
- Filtragem por pipeline/estágio feita no backend (ineficiente)
- Sem dead letter queue para mensagens que falham
- Lógica de coleta de dados misturada com lógica de IA

---

### 1.3 Knowledge Base (`inchurch-knowledge-production`)
**Stack:** Flask + Supabase + Pinecone + OpenAI Embeddings
**Responsabilidades:**
- API REST para Central de Ajuda (artigos, categorias)
- `GET /api/articles` — lista com paginação e filtros
- `GET /api/articles/:slug` — artigo individual
- `GET /api/categories` — lista categorias
- `GET /api/categories/popular` — categorias populares
- Integração com pipeline de vectorização (HubSpot GraphQL → chunking → embeddings → Pinecone → Supabase)
- Suporte multilíngue (pt-BR, en, es)

**Problemas identificados:**
- Flask não é async (bottleneck de performance)
- Sem cache (cada request bate no Supabase)
- Sem rate limiting
- Sem versionamento de API

---

### 1.4 Backoffice / Atribuição-Suporte (`inchurch-backoffice`)
**Stack:** Django + Django Ninja + Docker + PostgreSQL
**Responsabilidades:**
- Busca de igrejas via API externa (`/api/church/search`)
- Processamento de dados de igrejas (plano, status, gateways de pagamento)
- Interface administrativa para operações de suporte
- Proxy para APIs internas da plataforma InChurch

**Problemas identificados:**
- Python 3.12 (desatualizado)
- Sem autenticação JWT
- Dependência direta de API externa sem circuit breaker
- Sem documentação de negócio dos endpoints

---

### 1.5 Helper CX (`helper-cx-production`)
**Stack:** FastAPI + Supabase
**Responsabilidades:**
- Plataforma de automação de helpdesk
- Gestão de tickets e workflows
- Métricas e analytics de atendimento
- Integração com Heimdall Agent (triagem IA via N8N)
- Gestão de agentes e status de atendimento

**Problemas identificados:**
- Frontend e backend acoplados na mesma base de código
- Sem separação clara de domínios
- Sem testes automatizados
- Sem CI/CD estruturado

---

## 2. Mapa de Domínios do JUDAH

Após análise, os 5 backends convergem em **6 domínios de negócio**:

| Domínio | Origem | Descrição |
|---------|--------|-----------|
| **AI Agents** | Salomão v1 + WhatsApp | Agentes IA (RAG, triagem, conversação) |
| **Knowledge** | Knowledge Base | Artigos, categorias, busca semântica |
| **Support** | Helper CX + Heimdall | Tickets, filas, métricas, SLA |
| **Church** | Backoffice | Dados de igrejas, planos, gateways |
| **Integrations** | Todos | HubSpot, Jira, N8N, webhooks |
| **Auth & Core** | Novo | Autenticação, permissões, config |

---

## 3. Arquitetura do JUDAH

```
┌─────────────────────────────────────────────────────────────────┐
│                        JUDAH BACKEND                            │
│                  Python 3.14 + Django 5.2 LTS                   │
│                     Django Ninja 1.6.2                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   Auth   │ │  Church  │ │ Support  │ │Knowledge │           │
│  │   App    │ │   App    │ │   App    │ │   App    │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │             │            │             │                 │
│  ┌────┴─────┐ ┌─────┴────┐ ┌────┴─────┐ ┌────┴─────┐           │
│  │ AI Agents│ │Integra-  │ │ Webhooks │ │ Analytics│           │
│  │   App    │ │  tions   │ │   App    │ │   App    │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │             │            │             │                 │
├───────┴─────────────┴────────────┴─────────────┴────────────────┤
│                     SHARED LAYER (common/)                      │
│  Exceptions │ Pagination │ Permissions │ Cache │ Observability  │
├─────────────────────────────────────────────────────────────────┤
│                     INFRASTRUCTURE                              │
│  Supabase │ Redis │ Pinecone │ Celery │ HubSpot │ Jira │ Agno  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Stack Tecnológica Definida

### Core
| Tecnologia | Versão | Finalidade |
|-----------|--------|------------|
| Python | 3.14.0 | Runtime |
| Django | 5.2 LTS | Framework web |
| Django Ninja | 1.6.2 | API REST (Pydantic v2, OpenAPI 3.1) |
| Pydantic | 2.x | Validação e serialização |
| Uvicorn | latest | ASGI server |
| Gunicorn | latest | Process manager |

### Database & Cache
| Tecnologia | Finalidade |
|-----------|------------|
| Supabase (PostgreSQL) | Banco principal (igrejas, tickets, artigos, métricas) |
| Redis | Cache, sessões, rate limiting, Celery broker |
| Pinecone | Vector store para RAG |

### AI & Agents
| Tecnologia | Finalidade |
|-----------|------------|
| Agno 2.5.x | Framework de agentes IA (substitui OpenAI Assistants) |
| OpenAI API | LLM provider (GPT-4o, embeddings) |
| Anthropic API | LLM provider alternativo (Claude) |
| PgVector (via Agno) | Busca híbrida para RAG |

### Integrações
| Tecnologia | Finalidade |
|-----------|------------|
| HubSpot API | CRM, tickets, conversas |
| Jira API | Gestão de bugs e tasks |
| Celery + Redis | Tarefas assíncronas e agendadas |
| django-ninja-jwt | Autenticação JWT |

### DevOps & Observabilidade
| Tecnologia | Finalidade |
|-----------|------------|
| Docker + Compose | Containerização |
| Sentry | Error tracking |
| Structlog | Logging estruturado |
| pytest + coverage | Testes |
| Ruff | Linter + formatter (substitui Black/isort/flake8) |
| pre-commit | Git hooks |

---

## 5. Fases de Implementação

### Fase 1 — Fundação (Semanas 1-2)
- Estrutura do projeto Django + Docker
- Settings modulares (base, dev, prod)
- Auth app com JWT
- Health checks e docs OpenAPI
- CI/CD básico

### Fase 2 — Domínios Core (Semanas 3-5)
- Church app (migração do Backoffice)
- Knowledge app (migração da Knowledge Base)
- Support app (migração do Helper CX)

### Fase 3 — IA & Agentes (Semanas 6-8)
- AI Agents app com Agno
- Salomão RAG agent (Pinecone + knowledge)
- Heimdall triage agent
- WhatsApp bot agent

### Fase 4 — Integrações (Semanas 9-10)
- Integrations app (HubSpot, Jira)
- Webhooks app com dead letter queue
- Analytics app com métricas em tempo real

### Fase 5 — Hardening (Semanas 11-12)
- Testes de integração e carga
- Rate limiting + circuit breakers
- Observabilidade completa
- Documentação final

---

## 6. Decisões Arquiteturais

1. **Django Ninja sobre FastAPI puro:** Mantém o ecossistema Django (ORM, admin, migrations) com performance de FastAPI via Pydantic v2 + async nativo.

2. **Agno sobre LangChain/CrewAI:** Runtime de agentes stateless, horizontalmente escalável, com memory, knowledge e guardrails nativos. Roda como FastAPI nativo — se integra naturalmente ao Django Ninja.

3. **Supabase como banco principal:** Já em uso em múltiplos backends, PostgreSQL robusto, RLS nativo, real-time subscriptions para métricas.

4. **Redis como camada de cache e broker:** Sessões, rate limiting, cache de artigos, broker do Celery para tarefas async.

5. **Monorepo com apps Django:** Cada domínio é um Django app independente com schemas, services e API próprios — facilita manutenção e testes isolados.

6. **Ruff em vez de Black + isort + flake8:** Ferramenta all-in-one escrita em Rust, 10-100x mais rápida, configuração única no `pyproject.toml`.
