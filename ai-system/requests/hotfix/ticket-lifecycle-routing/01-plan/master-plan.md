# Hotfix plan

## Acceptance criteria

1. An explicit human request sends the confirmation first, then patches the
   ticket to `HUBSPOT_SUPPORT_PIPELINE_ID / HUBSPOT_SUPPORT_NEW_STAGE_ID`.
2. If the current owner equals `HUBSPOT_SALOMAO_TICKET_OWNER_ID`, handoff
   clears it so the Matchmaker can assign N1. Any other owner is preserved.
3. `candidate_resolved` closes only after the reply is delivered and HubSpot
   accepts `HUBSPOT_AI_TRIAGE_PIPELINE_ID / HUBSPOT_CLOSED_STAGE_ID`.
4. AI closure assigns `HUBSPOT_SALOMAO_TICKET_OWNER_ID` when configured and
   no owner is already present; a human owner is never overwritten.
5. `waiting_customer` does not close the ticket.
6. A new incoming customer message reopens a closed conversation instance.
7. Failed provider mutations are audited and become retryable.
8. Effects are idempotent per conversation turn.

## Verification

- Focused workflow, lifecycle and HubSpot transport tests.
- Full Ruff lint and format checks.
- Mypy.
- Full local SQLite test suite under Python 3.14.
- Django system checks using test settings.
