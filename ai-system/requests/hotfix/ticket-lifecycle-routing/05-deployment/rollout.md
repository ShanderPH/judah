# Production rollout

## Required configuration

No new environment variable is required. The Salomão lifecycle deliberately
does not mutate `hubspot_owner_id`; ownership remains under HubSpot/Matchmaker
authority.

## Rollout

1. Merge the PR to `main`.
2. Deploy web and worker from the same commit and record the deployed SHA.
3. Verify one conclusive AI answer reaches `Triagem N1 / Fechado`.
4. Verify one explicit human request reaches `Support N1 / Novo`.
5. Confirm a manually assigned human owner is not overwritten.
6. Start an AI turn, move the ticket out of `Triagem N1 / Novo atendimento`
   before completion, and confirm no late Salomão message is published.
7. In an unassigned AI ticket, reply manually as an agent before the pending
   AI task completes and confirm the automated response is suppressed.
8. Simulate one transient HubSpot PATCH failure after a visible reply and
   confirm only the route/close effect is retried.

## Rollback

Rollback the application commit. Route and status transitions are the only
HubSpot ticket properties written by this lifecycle.
