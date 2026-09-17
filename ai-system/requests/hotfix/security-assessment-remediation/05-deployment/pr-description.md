Metrics endpoints allowed viewer/agent access, visitor-token issuance lacked the
sandbox capability, readiness exposed dependency exceptions, and auth refresh
accepted redirects that URL normalization could move to another origin.

This hotfix enforces manager/admin on the three Django metrics operations and
`sandbox.use` before HubSpot configuration or fetch. Readiness retains 200/503
semantics with stable public errors and safe correlated logs. Refresh validates
resolved origins and encoded input while preserving valid internal destinations
and cookie behavior.

Validation: RED captured before production edits; 849 backend tests passed, 43
PostgreSQL/Celery-specific skips, 90.57% coverage; 66 webapp tests passed; Ruff,
formatting, mypy, ESLint, TypeScript, production build and pre-commit passed.
SAST is clean on changed production Python; historical global findings remain.
An independent agent review found a percent-encoding regression, now fixed and
re-reviewed. Fourteen local HTTP redirect cases passed with zero requests to the
controlled second origin. Dependencies/providers are mocked; no remote DB tests.

Draft gate: real-browser navigation/recording remains pending because no browser
is connected. The HTTP harness is not full Next.js E2E. Human review, branch
protection and required checks remain mandatory before merge. No production deploy
or provider changes were executed; the existing Vercel integration created an
automatic PR preview. Rollback is a reviewed code revert;
there are no migrations or data changes.

Evidence and acceptance status:
`ai-system/requests/hotfix/security-assessment-remediation/03-verification/04-final-gates.md`.
