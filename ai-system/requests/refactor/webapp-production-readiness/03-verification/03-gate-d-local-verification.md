# V-03 — Gate D local verification

Data: 2026-07-29. Local-only; no business API, non-local database, HubSpot mutation or deploy.

| Command/proof | Result |
|---|---|
| `npm.cmd ci` | passed; deterministic lock install |
| `npm.cmd ls next eslint-config-next sharp --depth=1` | Next/eslint-config 16.2.12; sharp 0.35.0 override; no ELSPROBLEMS |
| `npm.cmd audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| `npm.cmd run lint` | passed |
| `npm.cmd run typecheck` | passed |
| `npm.cmd test` | 17 passed, 7 files |
| `npm.cmd run build` | passed; 15 routes; no workspace-root warning |
| `git diff --check` | passed |

## HTTP header smoke

- `/login`: CSP report-only with the exact theme SHA-256 hash, global security headers and no-store.
- `/sandbox-chat`: 307 to login while retaining its isolated HubSpot CSP allowlist and no-store.
- `/api/auth/session`: 401, no-store and caller `X-Request-ID` returned.
- unknown BFF path: 404 default-deny, no-store and caller `X-Request-ID` returned.

## Remaining V-03 evidence

Staging login/refresh/logout/expiry, role smokes, real CSP reports, log-sink redaction/retention and sandbox eligibility were not executed because staging/deploy access is a separate approval boundary. CSP remains report-only and HSTS remains disabled.
