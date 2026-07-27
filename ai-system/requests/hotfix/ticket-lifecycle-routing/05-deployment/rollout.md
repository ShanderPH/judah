# Production rollout

## Required configuration

Set `HUBSPOT_SALOMAO_TICKET_OWNER_ID` on both the Railway web and worker
services to the HubSpot **ticket owner ID** that should own AI-resolved cases.
This is not the Conversations actor/user ID.

An empty value is backward compatible: pipeline and status still change, but
the existing owner is preserved. A ticket that already has an owner also keeps
that owner, so the automatic close never replaces a human assignment.

## Rollout

1. Merge the PR to `main`.
2. Configure the owner variable before or with the deployment.
3. Deploy web and worker from the same commit.
4. Verify one conclusive AI answer reaches `Triagem N1 / Fechado`.
5. Verify one explicit human request reaches `Support N1 / Novo`.
6. Confirm a manually assigned human owner is not overwritten.
7. Start an AI turn, move the ticket out of `Triagem N1 / Novo atendimento`
   before completion, and confirm no late Salomão message is published.
8. In an unassigned AI ticket, reply manually as an agent before the pending
   AI task completes and confirm the automated response is suppressed.

## Rollback

Rollback the application commit. If only owner assignment is problematic,
clear `HUBSPOT_SALOMAO_TICKET_OWNER_ID`; route and status transitions continue
without changing owner.
