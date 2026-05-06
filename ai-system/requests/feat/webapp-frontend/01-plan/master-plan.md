# Master Plan

## Goal

Build a production-ready administrative frontend in a new root-level Next.js app that integrates only with the existing Judah backend.

## Technical approach

1. Create a standalone Next.js 16.2.4 app with App Router, TypeScript, HeroUI v3.0.3, and GSAP.
2. Keep all backend access centralized in a typed API client layer with auth-aware wrappers.
3. Use the backend JWT flow only:
   - login
   - refresh
   - me
   - authenticated fetch wrappers
4. Protect authenticated pages in the web layer and route unauthenticated users to login.
5. Implement the requested screens using real backend data where available:
   - login
   - dashboard
   - queue management
   - auto-assignment visibility
   - metrics
6. Surface missing backend capabilities as explicit read-only states or admin notices instead of inventing actions.

## Planned frontend structure

- `webapp/`
  - `app/`
  - `src/components/`
  - `src/features/`
  - `src/lib/api/`
  - `src/lib/auth/`
  - `src/hooks/`
  - `src/types/`

## API coverage plan

### Will integrate directly

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `GET /api/v1/health/`
- `GET /api/v1/support/queue/status/`
- `GET /api/v1/support/queue/pending/`
- `GET /api/v1/support/queue/assigned/`
- `GET /api/v1/support/queue/health/`
- `POST /api/v1/support/queue/sync-novo/`
- `GET /api/v1/support/queue/metrics/`
- `GET /api/v1/support/business-hours/`
- `GET /api/v1/support/special-schedules/`
- `GET /api/v1/analytics/reports/`

### Will not depend on as core UX

- `support/tickets/*` because the backend contract is inconsistent with the current models.

## Acceptance-aligned constraints

- No direct Supabase calls in frontend code.
- No fake admin actions for missing APIs.
- Strong TypeScript types derived from current backend schemas.
- Responsive authenticated admin shell with premium visual language.
- Compile-clean baseline and brief run documentation.

## Known backend gaps to expose in UI/documentation

- Email-only login is not guaranteed by current backend contract.
- No logout endpoint.
- No API for agent management CRUD.
- No API for assignment rule CRUD beyond business hours/special schedules.
- No API for manual reassignment.
- No API for agent metrics detail.
- Ticket CRUD endpoints appear inconsistent with current models.
