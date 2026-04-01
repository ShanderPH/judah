# Decisions & Changes Log

## 2026-04-01 — HubSpot Webhook Event Type Constraint Fix

### Issue
All HubSpot webhook calls were returning HTTP 500 errors due to a database constraint violation:
```
IntegrityError: new row for relation "webhook_events" violates check constraint "webhook_events_event_type_check"
```

### Root Cause
The `webhook_events` table had a check constraint that only allowed `conversation.*` event types:
- `conversation.creation`
- `conversation.deletion`
- `conversation.privacyDeletion`
- `conversation.propertyChange`
- `conversation.newMessage`

However, HubSpot was sending `ticket.propertyChange`, `contact.propertyChange`, and other CRM event types that were not in the allowed list.

### Fix Applied
1. **Database constraint updated** via Supabase migration to include all HubSpot event types:
   - `ticket.*` events (creation, deletion, propertyChange, associationChange, etc.)
   - `contact.*` events
   - `deal.*` events
   - `company.*` events
   - `unknown` fallback

2. **Code improvements**:
   - Updated `apps/webhooks/services.py` to properly route all HubSpot event types
   - Updated `apps/webhooks/handlers/hubspot_handler.py` to handle `conversation.*` events
   - Added Django migration `0003_update_event_type_check_constraint.py` to document the change

### Files Changed
- `apps/webhooks/services.py` — Improved event routing logic
- `apps/webhooks/handlers/hubspot_handler.py` — Added `_handle_conversation_event` function
- `apps/webhooks/migrations/0003_update_event_type_check_constraint.py` — New migration

---

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
