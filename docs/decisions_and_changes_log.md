# Decisions & Changes Log

## 2026-03-31 — Initial Foundation (feature/judah-foundation)

### Architecture Decisions

**1. Django Ninja over DRF**  
Chosen for native async support, Pydantic v2 integration, automatic OpenAPI docs, and streaming SSE support needed for Agno agent responses.

**2. Agno over LangChain**  
Agno 2.5 provides a more Pythonic, lightweight agent framework with built-in memory, storage, and team orchestration without the complexity overhead of LangChain.

**3. Supabase as primary database**  
Using Supabase (PostgreSQL) via `psycopg[binary]` with `dj-database-url` for connection string parsing. Supabase Python client used for realtime and storage features only.

**4. Separate `integrations/` app**  
All external service clients (HubSpot, Jira, Pinecone, Supabase) are isolated in `apps/integrations/` with singleton pattern and circuit breaker to prevent cascade failures.

**5. Dead-letter queue for webhooks**  
Failed webhooks retry up to 3 times, then move to `DeadLetterQueue` table for manual review, preventing data loss.

**6. Celery with django-celery-beat**  
Database-backed scheduler allows runtime schedule changes without redeployment.

**7. structlog over Python logging**  
Provides structured JSON logging with context variables (request_id) automatically bound per request via middleware.

**8. `common/` over Django apps for shared utilities**  
Utilities like `cache.py`, `rate_limit.py`, `circuit_breaker.py` don't need database models so they live in `common/` rather than as Django apps.

### Changed from Original Spec

- Added `apps/health/` app (health check endpoint referenced in `core/urls.py` but not in spec)
- Added `core/settings/test.py` for pytest isolation (implied by pyproject.toml `DJANGO_SETTINGS_MODULE = "core.settings.test"`)
- `AgentMemory` and `AgentStorage` in Agno agents are handled via session/trace models rather than Agno's built-in providers (avoids coupling to specific storage backends at init time)
