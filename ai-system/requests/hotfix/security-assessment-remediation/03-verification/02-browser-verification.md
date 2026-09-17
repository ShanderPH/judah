# SEC-04: local HTTP verification and browser limitation

Date: 2026-09-17. Executed by the dedicated browser-verification sub-agent.

## Result

14 local HTTP cases passed against the actual `webapp/app/auth/refresh/route.ts`
handler, transpiled with installed TypeScript targeting ES2022 and using installed
`NextRequest` / `NextResponse`. Two ephemeral HTTP origins were bound exclusively
to localhost. The controlled destination received **zero requests**. Both servers
closed in `finally`; the command exited with code 0.

Command (repository root):

```powershell
node ai-system/requests/hotfix/security-assessment-remediation/03-verification/02-browser-http-harness.cjs
```

| Case | HTTP result / Location |
| --- | --- |
| `/dashboard` | 307, same-origin `/dashboard` |
| Internal query and fragment | 307, preserved `/reports?range=week#summary` |
| Encoded percent in query | 307, preserved `/reports?discount=25%25` |
| Encoded percent in path | 307, preserved `/reports/25%25` |
| Protocol-relative second origin | 307, same-origin `/dashboard` |
| Slash plus backslash second origin | 307, same-origin `/dashboard` |
| Encoded backslash | 307, same-origin `/dashboard` |
| Double-encoded backslash | 307, same-origin `/dashboard` |
| Absolute second-origin URL | 307, same-origin `/dashboard` |
| Literal tab | 307, same-origin `/dashboard` |
| Encoded newline | 307, same-origin `/dashboard` |
| Malformed percent encoding | 307, same-origin `/dashboard` |
| Missing `next` | 307, same-origin `/dashboard` |
| Missing session with malicious `next` | 307, same-origin `/login` |

Every Location was asserted before following it with a local-only HTTP request;
the final local endpoint returned 200. Cookies are synthetic: the harness proves
the handler invokes the cookie-write path and the unauthenticated deletion path,
including an expired deletion header. It does not verify real session resolution,
production cookie options, middleware, reverse proxy headers, or the full Next.js
server. No credentials or tokens were loaded. Provider `fetch` is prohibited in
the handler VM; only explicit local HTTP requests occur in the harness.

## Browser gate remains incomplete

CUA `getBrowser({url: 'http://localhost:43171'})` returned
`No browser is available`. A follow-up `cua.getState()` confirmed
`{"apps":[],"browsers":[]}`. Neither `webapp/node_modules/playwright` nor
`webapp/node_modules/@playwright/test` exists. Nothing was installed and no
external network was used. The required real-browser navigation and recording
were therefore **not performed**; these HTTP results must not be labeled browser
or full Next.js E2E evidence.

## Harness calibration

Two preliminary harness attempts failed before the final passing execution:
the actual NextRequest normalized a numeric loopback hostname to `localhost`,
and TypeScript's default ES5 transpilation did not preserve string-spread
semantics in this isolated harness. Both were harness configuration issues,
resolved by binding localhost and targeting ES2022. No production edits were
made by this sub-agent; these failures are not product regressions or TDD RED.
