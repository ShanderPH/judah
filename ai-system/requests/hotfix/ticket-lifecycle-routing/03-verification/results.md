# Verification results

Date: 2026-07-27

## Automated gates

- Focused lifecycle/race/retry suite: `126 passed` on Python 3.14.4.
- Full suite: `924 passed, 10 skipped` on Python 3.14.4.
- Coverage: `90.06%`, above the required `90.00%`.
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
- Salomão never writes ticket owner; concurrent human ownership is preserved.
- Conclusive answer is delivered before automatic closure.
- Existing human owner is preserved during automatic closure.
- Clarification keeps the ticket open.
- Provider failure is audited and marked retryable.
- A failed route/close after a delivered reply resumes only the durable
  provider effect; the model and customer-visible reply are not repeated.
- Incoming message reopens a closed conversation instance.
- Wrong pipeline, wrong stage and human ownership stop execution before the
  model is called.
- A route change during model execution suppresses the pending reply before
  the HubSpot message endpoint is called.
- Safe suppression records a successful policy audit, leaves failure count at
  zero and never closes or reroutes the ticket.
- Changed customer turns and suppressed handoff confirmations are terminal,
  not retryable.

## Scope notes

No frontend artifact changed. A real HubSpot browser smoke is still required
after deploying the exact web/worker SHA; until that evidence and re-review
exist, this request remains in `VERIFY`.
