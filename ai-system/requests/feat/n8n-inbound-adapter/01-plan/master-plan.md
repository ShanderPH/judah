# JUDAH n8n inbound adapter plan

## Scope and boundaries

Implement durable HubSpot message intake and reliable n8n delivery without
reintroducing customer identification, triage, Matchmaker decisions, owner
changes, or bot response execution.

## Reused components

- Canonical HubSpot webhook routes and v1/v3 signature validation.
- `WebhookEvent` as the provider-facing immutable raw-event ledger.
- `ConversationInstance` as the source of active operational threads.
- Shared `HubSpotClient`, Celery configuration, and structured logging.

## Work packages

- **DB-01:** extend the ledger and add transactional outbox and reconciliation cursor models.
- **BE-01:** normalize HubSpot messages and implement one atomic ingestion service.
- **BE-02:** adapt `conversation.newMessage` intake without synchronous n8n I/O.
- **BE-03:** deliver immutable n8n payloads with HMAC, bounded retry, jitter, and dead-letter.
- **BE-04:** reconcile active HubSpot threads through the same ingestion service.
- **OPS-01:** add disabled-by-default settings, structured metrics, and operational docs.
- **V-01:** cover webhook, idempotency, outbox, reconciliation, migration, and regressions.

## Architectural decisions

1. The webhook persists the authenticated message envelope before returning and
   hydrates full thread/message data asynchronously through HubSpot.
2. A canonical key `sha256(hubspot:portal:thread:message)` is the unique identity
   shared by ledger, outbox, payload, headers, logs, and metrics.
3. Database locks only claim/finalize work; no external HTTP request runs inside
   a database transaction.
4. Periodic pollers are implemented but not added to the production Beat schedule.
5. The existing inbound HMAC implementation is reused unchanged because its
   modification requires separate pre-approval.
6. The untracked legacy n8n specification is preserved; new documentation states
   the implemented outbound boundary accurately.

## Risks

- HubSpot webhook envelopes do not contain full message text, so hydration must
  remain retryable and reconciliation is the recovery path.
- SQLite cannot prove PostgreSQL `SKIP LOCKED` semantics; database-level
  concurrency behavior needs PostgreSQL verification before rollout.
- Activation requires HubSpot `conversations.read`, n8n URL/secret provisioning,
  migrations, and explicit Beat schedule creation outside this task.
