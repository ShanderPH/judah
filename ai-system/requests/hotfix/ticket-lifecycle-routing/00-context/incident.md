# Incident context

## Evidence

- Ticket `47211840016` replied to the explicit human request and published the
  internal handoff observation, but remained in `Triagem N1 / Novo atendimento`.
- Ticket `47193890059` needs automatic closure when the Supervisor returns a
  conclusive answer and no human handoff is required.
- Ticket `47224464755` was already being handled by a human agent, but a
  previously queued Salomão task published a late automated answer at 12:50.
  The task had hydrated the ticket before the human participation and did not
  revalidate exclusive ownership immediately before its customer-visible
  write.
- Production logs recorded five `hubspot_webhook_event_skipped_bad_signature`
  events for the two tickets. They were emitted by the separately signed
  Salomão-Supremo app.
- The Salomão-Supremo subscription was disabled operationally with
  `active: false` before this hotfix continued. The canonical Judah webhook
  subscription remains active.

## Root causes

1. The application distinguished `candidate_resolved`, but always persisted
   `WAITING_FOR_CUSTOMER`; no provider-side close effect existed.
2. The original routing path made ownership decisions from a previously
   hydrated snapshot, which could overwrite a concurrent human assignment.
3. A terminal conversation could only reopen through the N1 entry property,
   so immediate automatic closure would otherwise risk dropping a later
   customer message on the same thread.
4. Reply delivery trusted the context captured before model execution. A route
   or owner change during inference could therefore make the pending answer
   stale without invalidating its outbound write.

## Constraints

- The visitor-visible reply must be delivered before routing or closure.
- Human handoff must land in `Support N1 / Novo`.
- Salomão must never mutate ticket ownership; HubSpot/Matchmaker is the owner
  authority.
- Clarifying questions must remain open.
- External writes require tool permission, idempotency and audit records.
- Salomão may act only in the exact configured AI pipeline and active stage.
- Human ownership or human participation always wins over a queued AI task.
