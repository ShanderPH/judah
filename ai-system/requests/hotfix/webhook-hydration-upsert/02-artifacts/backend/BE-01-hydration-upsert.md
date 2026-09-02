# BE-01 — Hydration upsert implementation

## Production changes

- `apps/webhooks/n8n_inbound.py`
  - adds `_insert_event_if_absent()` using conflict-safe insertion;
  - makes envelope retries converge without catching `IntegrityError`;
  - accepts `existing_event_id` and locks the originating envelope;
  - validates the envelope canonical key before mutation.
- `apps/webhooks/reconciliation.py`
  - passes the envelope UUID to canonical ingestion;
  - prevents provider failure from overwriting concurrent terminal states.

## Deliberately unchanged

- models, migrations, unique constraints, payload contract, task arguments,
  Celery schedules, delivery retry semantics, n8n configuration, and dead-letter
  records.
