# Incident context

## Evidence

- Ticket `47211840016` replied to the explicit human request and published the
  internal handoff observation, but remained in `Triagem N1 / Novo atendimento`.
- Ticket `47193890059` needs automatic closure when the Supervisor returns a
  conclusive answer and no human handoff is required.
- Production logs recorded five `hubspot_webhook_event_skipped_bad_signature`
  events for the two tickets. They were emitted by the separately signed
  Salomão-Supremo app.
- The Salomão-Supremo subscription was disabled operationally with
  `active: false` before this hotfix continued. The canonical Judah webhook
  subscription remains active.

## Root causes

1. The application distinguished `candidate_resolved`, but always persisted
   `WAITING_FOR_CUSTOMER`; no provider-side close effect existed.
2. Ticket route updates could set pipeline and stage, but not set or clear
   `hubspot_owner_id`.
3. A terminal conversation could only reopen through the N1 entry property,
   so immediate automatic closure would otherwise risk dropping a later
   customer message on the same thread.

## Constraints

- The visitor-visible reply must be delivered before routing or closure.
- Human handoff must land in `Support N1 / Novo`.
- Only the configured AI owner may be cleared by the AI handoff path.
- A human owner must never be overwritten by this flow.
- Clarifying questions must remain open.
- External writes require tool permission, idempotency and audit records.
