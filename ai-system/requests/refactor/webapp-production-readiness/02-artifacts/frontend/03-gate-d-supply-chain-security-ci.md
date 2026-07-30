# Gate D — supply chain, headers, logging and CI

## Implemented contracts

- Next.js and `eslint-config-next` are pinned together at 16.2.12.
- `sharp` is overridden to 0.35.0 because Next 16.2.12 still declares `^0.34.5`, which remained covered by a high-severity advisory.
- `npm ci` is the documented and CI installation path; Turbopack root is pinned to the WebApp directory.
- CSP is report-only. The shared theme bootstrap is authorized by SHA-256 hash; HubSpot origins exist only in the `/sandbox-chat` policy.
- Global `nosniff`, referrer and permissions policies are set. HSTS remains intentionally disabled pending topology validation.
- Auth, BFF, HubSpot token and administrative pages are private/no-store.
- Server routes emit allowlisted JSON logs and propagate a validated/generated `X-Request-ID` to Judah.
- HubSpot error response bodies are no longer logged.
- Root CI now has a WebApp lane for deterministic install, lint, typecheck, tests, build, production audit and JUnit artifact upload.

## Backend integration

The existing Judah `common.logging` contract already provides structlog context, secret/PII scrubbing and request correlation. Gate D therefore changes the WebApp boundary and propagates its correlation ID instead of creating a parallel backend logger.

## Rollback

- CSP remains report-only and can be removed independently from RBAC/auth.
- Dependency rollback is permitted only to another audited version with a regenerated lockfile and green build.
- HSTS and CSP enforcement are not part of this artifact.

## Limits

No staging/production configuration, external log sink, deploy, push, PR or merge was changed. Retention configuration and browser role smokes remain staging/release evidence gates.
