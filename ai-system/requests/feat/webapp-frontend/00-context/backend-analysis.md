# Backend Analysis

## Repository shape

- Backend is a Django 5.2 + Django Ninja API rooted at `core/urls.py`.
- Main routed domains available to the frontend are:
  - `api/v1/auth/*`
  - `api/v1/support/*`
  - `api/v1/analytics/*`
  - `api/v1/health/*`
- There is no existing frontend app in the repo yet.

## Auth flow

- API auth is JWT-based with `ninja_jwt.authentication.JWTAuth`.
- The backend returns raw token pairs from `POST /api/v1/auth/login`.
- Protected routes expect `Authorization: Bearer <access>`.
- Refresh is exposed at `POST /api/v1/auth/refresh`.
- Current user profile is exposed at `GET /api/v1/auth/me`.
- There is no logout endpoint.
- There is no backend-issued cookie session or HttpOnly session wrapper.
- Important mismatch for the requested UI:
  - `LoginRequest` accepts `username` + `password`, not `email` + `password`.
  - A frontend email-only login is not guaranteed by the current backend contract.

## Support and queue endpoints actually available

### Strongly usable today

- `GET /api/v1/support/queue/status/`
  - High-level online agent counts, eligible agent counts, queue depth.
- `GET /api/v1/support/queue/pending/`
  - Paginated pending conversations.
- `GET /api/v1/support/queue/assigned/`
  - Paginated assigned conversations with optional filters by `agent_owner_id` and `closed`.
- `GET /api/v1/support/queue/health/`
  - Rich diagnostics: absent agents, eligible agents, pending tickets, warnings, issues, latest assignments.
- `POST /api/v1/support/queue/sync-novo/`
  - Admin-style trigger to sync NOVO-stage tickets from HubSpot into the internal queue.
- `GET /api/v1/support/queue/metrics/`
  - Paginated daily queue metrics for the last N days.
- `GET /api/v1/support/business-hours/`
  - Current business-hours configuration plus live state.
- `GET /api/v1/support/special-schedules/`
  - Special schedule overrides.

### Available but currently risky / inconsistent

- `GET|POST|PATCH /api/v1/support/tickets/*`
  - `apps/support/api.py`, `apps/support/services.py`, and `apps/support/models.py` are inconsistent.
  - Service code references fields and relations not present in the current `Ticket` model.
  - Frontend should not depend on these endpoints as core UX until the backend contract is corrected.

## Auto-assignment capabilities exposed by API

- Read access exists for:
  - queue status
  - eligible/absent agents via queue health
  - current pending/assigned conversations
  - aggregate queue metrics
  - business hours / special schedules
- Administrative write access exists only for:
  - sync NOVO tickets
  - create/delete special schedules
- Missing for a full admin panel:
  - list all agents as a first-class API resource
  - update agent availability
  - update agent capacity
  - toggle `auto_assign_enabled`
  - manual assignment / reassignment endpoints
  - CRUD for assignment rules beyond business hours/special schedules

## Metrics data actually available

- `GET /api/v1/analytics/reports/`
  - Daily reports if data exists.
- `GET /api/v1/analytics/reports/{date}`
  - Single daily report by date.
- `GET /api/v1/support/queue/metrics/`
  - Daily queue performance metrics with `assignments_by_agent`.
- Queue health also exposes:
  - recent assignment logs
  - eligible agent load snapshot
  - pending queue pressure

## Metrics gaps for the requested frontend

- No public API for `AgentMetrics`.
- No public API for `AgentDailyTimeLog`.
- No public API for `ConversationReassignment`.
- No public API for system-wide time-series service health.
- `analytics_daily_reports` exists in Supabase but is currently empty.
- `analytics_metrics` and `analytics_agent_performance` also exist but there are no read endpoints for them in the admin surface requested.

## Supabase observations

- Supabase is used by the backend as the application PostgreSQL database.
- The frontend must not connect directly to Supabase.
- Relevant tables confirmed in the active Supabase project include:
  - `auth_users`
  - `agents`
  - `new_conversations`
  - `assigned_conversations`
  - `closed_conversations`
  - `assignment_logs`
  - `queue_performance_metrics`
  - `business_hours_config`
  - `special_schedules`
  - `analytics_daily_reports`

## Pagination and error contracts

- Standard pagination uses `limit` and `offset`.
- Paginated responses follow `{ count, next, previous, results }`.
- Custom exceptions are normalized as JSON with `detail`.
- Some endpoints may also return `errors` or `service` depending on exception type.

## Security and session implications for the frontend

- Session persistence must be handled in the webapp layer because the backend only returns tokens.
- Because there is no server-managed cookie session, the frontend should:
  - store tokens securely on the web tier
  - refresh access tokens through the backend
  - clear session state on refresh failure
- Route guards can rely on `GET /api/v1/auth/me`.

## Implementation impact

- The frontend can be fully implemented now for:
  - login
  - dashboard
  - queue monitoring
  - read-heavy auto-assignment visibility
  - metrics with currently available datasets
- The frontend must visibly document missing backend capabilities instead of faking controls.
