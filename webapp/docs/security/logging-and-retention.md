# Logging, correlation and retention

## Runtime contract

- The WebApp emits structured JSON only from server-side code.
- Event fields are allowlisted to request ID, route, method, upstream, status, outcome and error type.
- Passwords, JWTs, authorization headers, cookies, query strings and third-party response bodies are never logged.
- `X-Request-ID` is accepted only in a restricted format; otherwise the WebApp creates a UUID and propagates it to Judah.

## Operational policy

| Record | Retention | Access | Disposal |
|---|---:|---|---|
| WebApp application logs | 30 days | Production on-call and platform administrators, least privilege | Automatic expiry in the hosting log sink |
| Security/CSP reports | 30 days | Security and platform maintainers | Automatic expiry after triage window |
| Administrative action ledger | 365 days | Auditors and explicitly authorized managers/admins | Scheduled deletion/anonymization under the backend data policy |

Platform Engineering owns log-sink access reviews and retention configuration. Security owns quarterly sampling for redaction regressions. Retention changes require a documented privacy/security decision; source code must not silently extend it.

No external log-sink settings are changed by this Gate D implementation. Staging must verify the configured retention, access groups and redaction before CSP enforcement or production release.
