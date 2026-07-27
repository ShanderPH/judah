# Hotfix plan

## Acceptance criteria

1. An explicit human request sends the confirmation first, then patches the
   ticket to `HUBSPOT_SUPPORT_PIPELINE_ID / HUBSPOT_SUPPORT_NEW_STAGE_ID`.
2. Neither handoff nor AI closure writes `hubspot_owner_id`; ownership remains
   under HubSpot/Matchmaker authority.
3. `candidate_resolved` closes only after the reply is delivered and HubSpot
   accepts `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_CLOSED_STAGE_ID`.
4. A concurrent human assignment is never cleared or overwritten by Salomão.
5. `waiting_customer` does not close the ticket.
6. A new incoming customer message reopens a closed conversation instance.
7. Failed provider mutations are audited and become retryable.
8. Effects are idempotent per conversation turn.
9. The Supervisor starts only when the ticket is in
   `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_N1_NEW_STAGE_ID`, with no human
   owner or active human participation.
10. Eligibility is refreshed immediately before reply delivery. A stale reply
    is suppressed without closing, rerouting or retrying against the ticket.
11. After a visible reply succeeds, a failed route/close PATCH is persisted and
    retried as a dedicated effect; the model and customer reply are not rerun.
12. A changed customer turn or safe handoff suppression is terminal and does
    not consume the retry budget.
13. Every path that can invoke the Supervisor requires a current customer turn
    whose latest usable message is `INCOMING`; full-history fallback is not
    allowed.
14. A stale lifecycle retry is terminalized before instance preparation or
    model execution and cannot reuse a sibling thread instance silently.
15. A HubSpot ticket-close event converges every persisted ticket/thread
    instance associated with that ticket to `CLOSED`.
16. HubSpot message hydration records the PII-free `clientType` and
    `integrationAppId` origins in structured logs.

## Verification

- Focused workflow, lifecycle and HubSpot transport tests.
- Full Ruff lint and format checks.
- Mypy.
- Full local SQLite test suite under Python 3.14.
- Django system checks using test settings.
- Race tests for route changes and human takeover during model processing.
