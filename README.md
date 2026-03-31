# JUDAH — Backend Unificado InChurch

Backend unificado da InChurch, consolidando 5 serviços separados em uma única plataforma Django moderna e escalável.

## Visão Geral

JUDAH substitui:
- **Salomão v1** — Agente RAG de IA (FastAPI + OpenAI + Pinecone)
- **Salomão WhatsApp** — Bot HubSpot WhatsApp (FastAPI + HubSpot API)
- **Knowledge Base** — Central de Ajuda (Flask + Supabase + Pinecone)
- **Backoffice** — Operações de suporte (Django Ninja)
- **Helper CX** — Plataforma de helpdesk (FastAPI + Supabase)

## Stack Tecnológica

| Camada | Tecnologia |
|--------|-----------|
| Framework | Django 5.2 LTS |
| API | Django Ninja 1.6.2 |
| Auth | django-ninja-jwt |
| Banco de Dados | Supabase (PostgreSQL) via psycopg3 |
| Cache / Broker | Redis 7 |
| Tarefas Assíncronas | Celery 5 + django-celery-beat |
| IA / Agentes | Agno 2.5 + OpenAI GPT-4o |
| Vector Store | Pinecone |
| Servidor | Uvicorn (ASGI) + Gunicorn |
| Observabilidade | structlog + Sentry |
| Linting | Ruff |
| Testes | pytest + pytest-django + pytest-asyncio |

## Estrutura de Apps

```
apps/
├── auth_user/      # Usuários com papéis (admin, manager, agent, viewer)
├── church/         # Dados e operações de igrejas
├── knowledge/      # Central de ajuda com busca semântica
├── support/        # Helpdesk, tickets, filas, SLA
├── ai_agents/      # Agentes IA (Salomão + Heimdall)
├── integrations/   # HubSpot, Jira, Pinecone, Supabase
├── webhooks/       # Recepção de webhooks externos
└── analytics/      # Métricas e relatórios diários
```

## Setup Local

### Pré-requisitos

- Python 3.14+
- PostgreSQL 16+ (ou Docker)
- Redis 7+ (ou Docker)

### 1. Clonar e configurar ambiente

```bash
git clone <repo-url>
cd judah
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
```

### 2. Instalar dependências

```bash
pip install -r requirements/dev.txt
pre-commit install
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com suas credenciais
```

Variáveis obrigatórias:
- `DJANGO_SECRET_KEY` — chave secreta Django
- `DATABASE_URL` — URL PostgreSQL (Supabase)
- `REDIS_URL` — URL Redis
- `OPENAI_API_KEY` — chave OpenAI
- `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`

### 4. Aplicar migrações

```bash
make migrate
```

### 5. Criar superusuário

```bash
make superuser
```

### 6. Iniciar servidor

```bash
make run
```

A API estará disponível em `http://localhost:8000/api/v1/`  
Documentação Swagger: `http://localhost:8000/api/v1/docs`

## Docker Compose

Para subir o ambiente completo localmente:

```bash
make docker-up
```

Serviços disponíveis:
- `app` → `http://localhost:8000`
- `db` → `localhost:5432`
- `redis` → `localhost:6379`
- Celery worker + beat

```bash
make docker-down   # parar
make docker-logs   # ver logs
```

## Comandos Make

| Comando | Descrição |
|---------|-----------|
| `make run` | Inicia Uvicorn (desenvolvimento) |
| `make test` | Executa pytest com coverage |
| `make lint` | Ruff check + format (com correções) |
| `make lint-check` | Ruff sem correções (modo CI) |
| `make migrate` | Aplica migrações |
| `make migrations` | Gera novas migrações |
| `make shell` | Abre Django shell (IPython) |
| `make superuser` | Cria superusuário admin |
| `make celery` | Inicia worker Celery |
| `make celery-beat` | Inicia scheduler Celery Beat |
| `make docker-up` | Sobe todos os serviços Docker |
| `make docker-down` | Para os serviços Docker |

## Endpoints da API

### Auth (`/api/v1/auth/`)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/register` | Registrar novo usuário |
| POST | `/login` | Login (retorna JWT) |
| POST | `/refresh` | Renovar access token |
| GET | `/me` | Perfil do usuário autenticado |
| PATCH | `/me` | Atualizar perfil |
| POST | `/me/change-password` | Alterar senha |

### AI Agents (`/api/v1/ai/`)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/chat/` | Chat com Salomão |
| POST | `/triage/` | Triagem com Heimdall |

### Knowledge Base (`/api/v1/knowledge/`)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/articles/` | Listar artigos publicados |
| GET | `/articles/{slug}` | Buscar artigo por slug |
| POST | `/search/` | Busca semântica |

### Support (`/api/v1/support/`)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/tickets/` | Listar tickets |
| POST | `/tickets/` | Criar ticket |
| GET | `/tickets/{id}` | Buscar ticket |
| PATCH | `/tickets/{id}` | Atualizar ticket |

### Health (`/api/v1/health/`)
| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/` | Health check (db + cache) |

## Testes

```bash
# Todos os testes
make test

# Com relatório HTML
pytest --cov=apps --cov=common --cov-report=html

# Apenas um app
pytest apps/auth_user/tests/ -v

# Marcar como lento
pytest -m "not slow"
```

## Arquitetura dos Agentes IA

```
ai_agents/
├── agents/
│   ├── salomao.py    # Agente de suporte ao cliente (GPT-4o)
│   ├── heimdall.py   # Agente de triagem (GPT-4o-mini)
│   └── tools/
│       ├── knowledge_tools.py   # Busca na KB via Pinecone
│       ├── hubspot_tools.py     # Tickets e contatos HubSpot
│       └── jira_tools.py        # Issues Jira
```

## Convenções de Código

- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/)
- **Branches**: `feature/`, `bugfix/`, `hotfix/`, `release/`, `chore/`
- **Estilo**: Ruff (PEP 8, linha máx 120 chars)
- **Type hints**: 100% do código público
- **Docstrings**: Todas as classes e funções públicas

## Troubleshooting

**Erro `DATABASE_URL not set`**  
→ Verifique se o `.env` existe e está preenchido.

**Erro de conexão Redis**  
→ Certifique-se de que o Redis está rodando: `redis-cli ping`

**Migrações falhando**  
→ Verifique `DATABASE_URL` e que a base existe: `psql -c "CREATE DATABASE judah_dev;"`

**Agentes retornando erro**  
→ Verifique `OPENAI_API_KEY` e `PINECONE_API_KEY` no `.env`
