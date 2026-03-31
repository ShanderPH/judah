# JUDAH — Foundation Setup

## Overview

Initial backend foundation for JUDAH, the unified InChurch backend consolidating 5 legacy services.

## What Was Built

### Project Configuration
- `pyproject.toml` — project metadata, Ruff and pytest configuration
- `requirements/base.txt`, `dev.txt`, `test.txt` — layered dependency management
- `.env.example` — complete environment variable template
- `.pre-commit-config.yaml` — pre-commit hooks (trailing whitespace, Ruff)
- `.gitignore` — comprehensive Python/Django gitignore

### Infrastructure
- `Dockerfile` — multi-stage production build (python:3.14-slim)
- `docker-compose.yml` — local dev stack (app, PostgreSQL 16, Redis 7, Celery worker + beat)
- `Makefile` — developer convenience targets

### Django Core (`core/`)
- `settings/base.py` — all shared settings (DB, cache, Celery, JWT, CORS, Sentry, structlog)
- `settings/development.py` — debug toolbar, eager Celery
- `settings/production.py` — security hardening headers
- `settings/test.py` — fast test settings (MD5 hasher, LocMemCache)
- `urls.py` — NinjaAPI root with all routers registered at `/api/v1/`
- `asgi.py`, `wsgi.py`, `celery.py`

### Apps

| App | Key Models | Features |
|-----|-----------|---------|
| `auth_user` | `User` (AbstractUser + role + HubSpot) | JWT login/register, profile update, change password, full test suite |
| `church` | `Church`, `Plan`, `Gateway` | CRUD, external ID lookup |
| `knowledge` | `Article`, `Category`, `ArticleChunk` | Semantic search via Pinecone, CRUD |
| `support` | `Ticket`, `Queue`, `SLA`, `Agent`, `Metric` | Full helpdesk, status/priority filters |
| `ai_agents` | `AgentSession`, `AgentMemory`, `AgentTrace` | Salomão (GPT-4o RAG) + Heimdall (triage), Agno framework |
| `integrations` | — | HubSpot client, Jira client, Pinecone client, Supabase client |
| `webhooks` | `WebhookEvent`, `DeadLetterQueue` | HubSpot + Jira webhook receivers, dead-letter queue |
| `analytics` | `Metric`, `DailyReport`, `AgentPerformance` | Daily reports, Celery aggregation tasks |
| `health` | — | `GET /api/v1/health/` checks DB + cache |

### Common Utilities (`common/`)
- `exceptions.py` — typed exceptions + Ninja exception handlers
- `pagination.py` — standard offset + cursor pagination
- `permissions.py` — role-based access decorators
- `cache.py` — Redis cache decorator + prefix invalidation
- `rate_limit.py` — sliding-window rate limiting middleware
- `circuit_breaker.py` — resilience pattern for external APIs
- `middleware.py` — structured request/response logging with X-Request-ID
- `utils.py` — slugify, truncate, mask_secret, uuid, utcnow

### AI Agents
- `salomao.py` — Agno `Agent` with GPT-4o, knowledge base + HubSpot tools
- `heimdall.py` — Agno `Agent` with GPT-4o-mini for triage + Jira escalation
- `knowledge_tools.py`, `hubspot_tools.py`, `jira_tools.py` — Agno `Toolkit` classes

## Architecture Decisions

- **Services layer**: all business logic in `services.py`, never in API endpoints
- **Lazy imports**: external integrations use deferred imports to avoid circular dependencies
- **Singleton clients**: HubSpot, Jira, Pinecone, Supabase use module-level singletons
- **Circuit breaker**: wraps all external API calls in `common.circuit_breaker.CircuitBreaker`
- **Pydantic v2**: all API schemas use `ninja.Schema` (Pydantic v2 under the hood)
- **Type hints**: 100% on all public functions and methods

## Git Branch

`feature/judah-foundation`
