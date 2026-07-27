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
- Ticket `47206585351` exposed a second stale-processing path: a human moved
  the ticket back to `IA / NOVO` without a new visitor turn. The ticket-level
  worker and a later lifecycle retry could rebuild input from old history,
  while ticket and thread lifecycle instances diverged on closure.
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
5. Ticket-triggered processing allowed a full-history fallback when the latest
   usable message was not `INCOMING`.
6. Ticket closure updated only the ticket placeholder instance and did not
   converge thread instances associated with the same ticket.

## Constraints

- The visitor-visible reply must be delivered before routing or closure.
- Human handoff must land in `Support N1 / Novo`.
- Salomão must never mutate ticket ownership; HubSpot/Matchmaker is the owner
  authority.
- Clarifying questions must remain open.
- External writes require tool permission, idempotency and audit records.
- Salomão may act only in the exact configured AI pipeline and active stage.
- Human ownership or human participation always wins over a queued AI task.
