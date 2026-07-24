# JUDAH — Backend Unificado InChurch

**Status:** Pre-production. See [Known Risks](#known-risks--pre-production-checklist) before deploying.

Backend unificado da InChurch: uma plataforma Django 5.2 que consolida suporte, base de conhecimento, analytics e agentes de IA em um único serviço. Substitui os legados **Salomão v1**, **Salomão WhatsApp**, **Knowledge Base**, **Backoffice** e **Helper CX**.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Repository Layout](#repository-layout)
4. [Local Setup](#local-setup)
5. [Configuration](#configuration)
6. [Running the API, Worker, and Scheduler](#running-the-api-worker-and-scheduler)
7. [AI / Agent Architecture](#ai--agent-architecture)
8. [Security Considerations](#security-considerations)
9. [Testing](#testing)
10. [Developer Guidelines](#developer-guidelines)
11. [Deployment (Railway)](#deployment-railway)
12. [Known Risks — Pre-production Checklist](#known-risks--pre-production-checklist)

---

## Architecture Overview

```
                     ┌──────────────────────────┐
 HubSpot ────────────►  /api/v1/webhooks/       │
                     │  (HMAC v1+v3 verified)   │
                     └────────────┬─────────────┘
                                  │
                   (Celery task)  ▼
                     ┌──────────────────────────┐
                     │  Auto-assignment queue   │
                     │  (Matchmaker + SAT)      │
                     └────────────┬─────────────┘
                                  │
                                  ▼
 Authenticated UI ───► /api/v1/ai/salomao/chat ─► SalomaoSupervisorAgent
                                                    │
                                                    ▼
                                             HeimdallTriage
                                                (gpt-5.5)
                                                    │
                                                    ▼
                                             SalomaoChat adapter
                                                    │
                                                    ▼
                                              Salomao v1
                                                (gpt-5.5)
```

The production **Supervisor** calls Heimdall first to produce a structured `TriageResult`, then always delegates the customer answer to the official Salomao v1 adapter. Only `ESCALAR_IMEDIATAMENTE`, an unavailable v1 service, or a transfer requested by v1 enters human handoff. Sessions are persisted to Redis, keyed by `user-{id}` or `hubspot-ticket-{id}`.

Background work (pipeline dispatch, auto-assignment, metrics aggregation) is scheduled by Celery. FastAPI-style endpoints are exposed through **Django Ninja**.

---

## Tech Stack

| Layer              | Choice                                          |
|--------------------|-------------------------------------------------|
| Runtime            | Python 3.14 (**exact version required**)        |
| Framework          | Django 5.2 LTS + Django Ninja 1.6               |
| Auth               | django-ninja-jwt (HS256)                        |
| Database           | PostgreSQL 16 (Supabase in dev/prod)            |
| Cache / Broker     | Redis 7                                         |
| Async workers      | Celery 5 + django-celery-beat                   |
| AI runtime         | Agno 2.5 (agents, teams, knowledge)             |
| Model providers    | OpenAI (GPT-4o, GPT-4o-mini), Anthropic fallback|
| Vector store       | Pinecone serverless                             |
| Tool protocol      | MCP 1.x (FastMCP server for HubSpot)            |
| Observability      | structlog + Sentry + request IDs                |
| Server             | Uvicorn (ASGI) / Gunicorn                       |
| Lint / format      | Ruff (target py314)                             |
| Tests              | pytest + pytest-django + pytest-asyncio         |

---

## Repository Layout

```
apps/
├── auth_user/      # Custom User model with roles (admin, manager, agent, viewer)
├── church/         # Church domain objects
├── knowledge/      # Help center articles + semantic search
├── support/        # Tickets, queues, SAT, auto-assignment, matchmaker
├── ai_agents/      # Salomão supervisor + Heimdall, RAG, Action agents
│   ├── agents/          # BaseInChurchAgent + sub-agents (triage, rag, action)
│   ├── api/             # /ai/salomao/chat + webhooks
│   ├── mcp_servers/     # FastMCP HubSpot server
│   ├── services/        # HubSpot hydration, pricing
│   └── utils/           # Business rules (timezone, holidays)
├── integrations/   # HubSpot, Jira, Pinecone, Supabase clients
├── webhooks/       # Canonical inbound webhook router (HubSpot, Jira)
└── analytics/      # Daily metrics aggregation

common/
├── circuit_breaker.py   # Process-local breaker (see Known Risks)
├── exceptions.py        # JudahError hierarchy + Ninja handlers
├── logging.py           # structlog config + correlation IDs
├── middleware.py        # RequestLoggingMiddleware
└── rate_limit.py        # Redis sliding-window limiter

core/
├── settings/            # base / development / production / test (selected by DJANGO_ENV)
├── urls.py              # NinjaAPI root + router registration
└── celery.py            # Celery app factory
```

---

## Local Setup

### Prerequisites

- **Python 3.14** (exact — see [Known Risks](#known-risks--pre-production-checklist))
- PostgreSQL 16 (or Supabase project)
- Redis 7

### 1. Clone and create venv

```bash
git clone <repo-url>
cd judah
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements/dev.txt
pre-commit install
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — do NOT commit
```

### 4. Migrate and create superuser

```bash
make migrate
make superuser
```

---

## Configuration

All secrets and environment-specific settings are loaded via `python-decouple`. The full set is in `.env.example`; the runtime-required subset is:

| Variable                        | Required           | Notes                                                   |
|---------------------------------|--------------------|---------------------------------------------------------|
| `DJANGO_SECRET_KEY`             | Always             | Used for Django AND as JWT signing key (see S-08)       |
| `DJANGO_DEBUG`                  | No (default False) | `True` enables a permissive webhook signature bypass    |
| `DJANGO_ALLOWED_HOSTS`          | Production         | Comma-separated                                         |
| `DATABASE_URL`                  | Always             | `postgres://...`                                        |
| `REDIS_URL`                     | Always             | Broker, cache, and agent session store                  |
| `AI_ROUTING_ENABLED`            | AI endpoints       | Mounts `/api/v1/ai/*` when `true`                       |
| `AI_ROUTING_ROLLOUT_PERCENTAGE` | AI routing         | Stable rollout cohort from `0` to `100`; default `100` |
| `OPENAI_API_KEY`                | AI endpoints       | For GPT-4o / 4o-mini and embeddings                     |
| `PINECONE_API_KEY`              | RAG                | Pinecone serverless                                     |
| `PINECONE_INDEX_NAME`           | RAG                |                                                         |
| `PINECONE_HOST`                 | RAG (recommended)  | Data-plane URL — avoids cloud/region guessing           |
| `SALOMAO_V1_BASE_URL`           | Salomao v1 adapter | When set, the Supervisor can expose Salomao v1 as an internal Team member |
| `SALOMAO_V1_TIMEOUT_SECONDS`    | Salomao v1 adapter | HTTP timeout for the Salomao v1 adapter                 |
| `SALOMAO_V1_AS_TEAM_AGENT`      | Salomao v1 adapter | Enables the internal `SalomaoChat` Team member, default `true` |
| `SALOMAO_V1_MAX_ATTEMPTS`       | Salomao v1 adapter | Retries for timeout, HTTP 429, and HTTP 5xx; default `3` |
| `SALOMAO_MIN_CONFIDENCE`        | AI policy         | Minimum Salomao draft confidence before human handoff; default `0.65` |
| `HEIMDALL_MIN_CONFIDENCE`       | AI policy         | Minimum Heimdall confidence before human handoff; default `0.65` |
| `HUBSPOT_ACCESS_TOKEN`          | Webhooks / MCP     | Private-app token                                       |
| `HUBSPOT_APP_SECRET`            | **Production**     | Signs v1+v3 webhooks — **never leave blank in prod**    |
| `HUBSPOT_SALOMAO_SENDER_ACTOR_ID` | HubSpot chat AI   | HubSpot actor ID used by Salomao to answer conversation threads |
| `HUBSPOT_TICKET_CHURCH_PROPERTY` | HubSpot protocol lookup | Ticket property containing the local church ID; defaults to `codigo_de_igreja_local___ticket` |
| `HUBSPOT_PORTAL_ID`             | Optional           | Used to build ticket URLs                               |
| `SENTRY_DSN`                    | Recommended        | Auto-initialized if set                                 |
| `DEFAULT_MODEL`                 | Optional           | Override `gpt-5.5`                                      |
| `DEFAULT_MINI_MODEL`            | Optional           | Override `gpt-5.5`                                      |
| `USE_MOCK_HUBSPOT`              | Dev only           | `True` bypasses signature verification (local simulator)|

---

## Running the API, Worker, and Scheduler

| Target         | Command                    |
|----------------|----------------------------|
| API (dev)      | `make run`                 |
| API (prod)     | `python scripts/start_service.py` |
| Celery worker  | `make celery`              |
| Celery beat    | `make celery-beat`         |
| Full stack     | `make docker-up`           |

The production launcher applies pending migrations before accepting traffic.
Render automatically provides `RENDER=true`, so a Free Web Service also starts
one low-memory Celery worker with embedded beat in the same container. Set
`RUN_CELERY_IN_WEB=false` only when a dedicated worker and beat are deployed.

OpenAPI docs: `http://localhost:8000/api/v1/docs`

---

## AI / Agent Architecture

### Primary entry point

`POST /api/v1/ai/salomao/chat` (JWT-authenticated) → `SalomaoSupervisorAgent.run_pipeline_async()`.

### Supervisor flow

1. **Circuit breaker** — reject if the session has consumed >15k tokens (`TokenTrackingLog` aggregate). See Known Risks H4.
2. **Greeting injection** — first-turn system rule prepended to Team instructions (per-request).
3. **Deterministic chain** — Judah coordinates:
   - `HeimdallTriageAgent` (gpt-5.5, `output_schema=TriageResult`) classifies the message.
   - `SalomaoChatAgent` sends the current customer turn, triage and normalized history to Salomao v1.
   - Judah preserves the complete Markdown response from v1.
   - `ESCALAR_IMEDIATAMENTE`, v1 unavailability, or a v1 transfer request triggers human handoff.
4. **Token tracking** — tokens × model price persisted to `TokenTrackingLog` (see `utils/pricing.py`).

### MCP integration

`apps/ai_agents/mcp_servers/hubspot_server.py` is a FastMCP server exposing `get_ticket_status`, `create_helpdesk_ticket`, and `update_ticket`. It runs as a stdio subprocess spawned by the `HelpdeskActionAgent`. No persistent state.

### Inbound webhook pipeline

`POST /api/v1/webhooks/hubspot/` is the canonical and authoritative webhook
router. It verifies HubSpot HMAC v1/v3 (including the v3 replay window),
persists provider-aware idempotency, and schedules durable processing through
Celery. `RoutingPolicyEngine` selects exactly one deterministic route before
any LLM call. AI routes hydrate a normalized `ConversationContext`, run
content-safety checks, execute Heimdall, and apply the resulting
`SupervisorDecision` through an audited backend execution layer.

Candidate resolutions and focused questions enter `WAITING_FOR_CUSTOMER`.
Only explicit customer confirmation closes an AI-resolved conversation.
Human handoffs persist a `HandoffPackage` and enter Matchmaker. Watchdog and
retry tasks recover stuck or transiently failed executions.

### Session persistence

Agno sessions are stored in Redis under `inchurch:agent:{session_id}`. `session_id` is derived from:
- `user-{request.user.pk}` for authenticated chat
- `hubspot-ticket-{ticket_id}` for webhook-triggered runs

---

## Security Considerations

1. **Webhook signatures.** HubSpot webhooks are verified via v1 SHA-256 or v3
   HMAC. Production fails closed when `HUBSPOT_APP_SECRET` is absent.
2. **JWT.** HS256 using `DJANGO_SECRET_KEY`. Rotating the secret invalidates every active session.
3. **Rate limiting.** `common/rate_limit.py` applies a sliding window per user or IP. Race-prone under high load — see risk H8.
4. **CORS.** Explicit origin whitelist via `CORS_ALLOWED_ORIGINS`. Credentials allowed.
5. **Prompt injection.** Customer content is normalized and explicit
   instruction-override patterns are handed off before LLM execution. This
   deterministic guardrail must still be backed by evals and monitoring.
6. **Secrets in logs.** `debug_mode=True` is still hardcoded on several agents — these expose prompts and tool arguments in logs. Disable before shipping.
7. **PII.** No encryption at rest for agent traces; rely on the database's TDE (Supabase).
8. **MCP subprocess.** Inherits the parent env — strip secrets before passing downstream once `env` kwarg usage is audited.

---

## Testing

```bash
make test                    # pytest with coverage
pytest apps/support/tests/   # one app
pytest -m "not slow"         # skip slow suite
```

**Warning:** `conftest.py:isolate_db` deletes rows from the support tables before every test. If `DATABASE_URL` points at production, this rolls back within the transaction **only** when Django actually opens one. Always confirm you are pointed at a disposable database.

Coverage floor: 90% (`pyproject.toml` and CI). The suite uses a private local
SQLite database through `python run_tests_local.py`; never load production
credentials into pytest.

---

## Developer Guidelines

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/).
- **Branches:** `feature/`, `bugfix/`, `hotfix/`, `release/`, `chore/`.
- **Style:** Ruff; `line-length = 120`, `target-version = py314`.
- **Types:** 100% on public APIs; `from __future__ import annotations` in new files.
- **Docstrings:** Mandatory on public classes, functions, and MCP tools (LLMs read them).
- **Logs:** Use `structlog`. Never log secret prefixes; never log full request bodies.
- **Migrations:** Generate with `make migrations`, review manually, name descriptively.

---

## Deployment (Railway)

- `Dockerfile` — API container
- `Dockerfile.worker` — Celery worker
- `Dockerfile.beat` — Celery beat
- `railway.toml` / `railway.worker.toml` / `railway.beat.toml` — service declarations

Railway terminates TLS at the edge; Django trusts `X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`). Do not enable `SECURE_SSL_REDIRECT` — it breaks the internal health check (see `core/settings/production.py`).

`ALLOWED_HOSTS` is extended automatically to include `.railway.app` and `healthcheck.railway.app`.

### Salomao v1 adapter on Railway

For a real HubSpot chat test without ngrok, deploy both services on Railway:

1. **Salomao v1 service** exposes `POST /chat` and `GET /health`.
2. **Judah API service** receives HubSpot webhooks and runs the Supervisor.
3. **Judah worker service** runs Celery tasks for webhook processing.

Set these variables on the Judah API and worker services:

```env
AI_ROUTING_ENABLED=true
AI_ROUTING_ROLLOUT_PERCENTAGE=100
SALOMAO_V1_BASE_URL=https://salomao-v1-production.up.railway.app
SALOMAO_V1_TIMEOUT_SECONDS=120
SALOMAO_V1_AS_TEAM_AGENT=true
SALOMAO_V1_MAX_ATTEMPTS=3
SALOMAO_MIN_CONFIDENCE=0.65
HEIMDALL_MIN_CONFIDENCE=0.65
HUBSPOT_ACCESS_TOKEN=...
HUBSPOT_APP_SECRET=...
HUBSPOT_SALOMAO_SENDER_ACTOR_ID=...
```

Then configure the HubSpot webhook URL:

```text
https://judah-production.up.railway.app/api/v1/webhooks/hubspot/
```

Subscribe the app to:

```text
conversation.newMessage
```

The runtime flow is:

```text
HubSpot chat -> Judah Railway webhook -> Judah Celery worker -> Supervisor -> SalomaoChat member -> Salomao v1 Railway -> HubSpot thread reply
```

---

## Known Risks — Pre-production Checklist

The following must be resolved before production cutover. See the full audit report for detail.

- [x] **C1** — Fail-closed when `HUBSPOT_APP_SECRET` is blank.
- [x] **C2** — Add a deterministic prompt-injection guardrail around ticket content.
- [x] **C3** — Replace `asyncio.create_task` in `ai_agents/api/webhooks.py` with a Celery task. *(Done — `run_supervisor_pipeline_task.delay` is used.)*
- [x] **C4** — Make `/api/v1/webhooks/hubspot/` the single mounted,
  authoritative entry point; the alternate router remains unmounted worker
  code.
- [ ] **C5** — Gate `conftest.py:isolate_db` behind an explicit test-env marker.
- [x] **H1** — Fix `except Ticket.DoesNotExist, ValueError:` in `support/services.py`. *(Done — syntax corrected.)*
- [ ] **H1b** — Audit `auto_assign_service.py` and `hubspot_handler.py` for any remaining Python 2 exception syntax.
- [ ] **H2** — Remove `debug_mode=True` from Salomão agents; remove the `loading_openai_key` log line.
- [ ] **H3** — Stop mutating `self._team.instructions` per request.
- [ ] **H4** — Switch the token budget to a rolling window.
- [x] **H5** — Use structured `TriageDecision` and `SupervisorDecision`
  contracts for routing and handoff outcomes.
- [ ] **H6** — Cache Pinecone / Knowledge / MCPTools at process startup.
- [ ] **H7** — Delete the legacy module-level `salomao_agent` / `heimdall_agent` + `services.chat_with_agent`.
- [ ] **H8** — Replace the custom rate limiter with an atomic implementation.
- [ ] **H9** — Move pipeline stage IDs into settings.
- [x] **H10** — Persist correlated Heimdall and Supervisor executions in
  `AgentRun`, including model, prompt and policy versions.

Once these are green the system can be promoted to production with a staged rollout.
