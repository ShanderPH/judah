# Verification results

Date: 2026-07-27

## Automated gates

- Full suite: `906 passed, 10 skipped` on Python 3.14.4.
- Coverage: `90.11%`, above the required `90.00%`.
- Ruff lint: clean.
- Ruff formatting: 338 files already formatted.
- Mypy: clean for 335 source files with the isolated test environment.
- Django system check: no issues.
- Migration check: no changes detected.
- `git diff --check`: clean.

## Acceptance coverage

- Human request is confirmed before the ticket is routed.
- Handoff effects are idempotent per customer turn and execute again for a new
  turn in the same conversation.
- Handoff targets Support/Novo in and out of business hours.
- AI owner is cleared for N1 assignment; human owner is preserved.
- Conclusive answer is delivered before automatic closure.
- Existing human owner is preserved during automatic closure.
- Clarification keeps the ticket open.
- Provider failure is audited and marked retryable.
- Incoming message reopens a closed conversation instance.

## Scope notes

No frontend or browser artifact changed, so browser smoke is not applicable to
this request. No production mutation or deployment was performed as part of the
local verification; the production smoke sequence is documented in
`05-deployment/rollout.md`.
