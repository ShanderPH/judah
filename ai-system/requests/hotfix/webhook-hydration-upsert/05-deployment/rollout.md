# Rollout and rollback

1. Capture a 30-minute production baseline for `23505`, ledger status, outbox
   cardinality, database waits, and latency.
2. Merge the emergency PR into `master` only after PostgreSQL 16 verification.
3. Deploy worker, then API, and align Beat to the same SHA without changing its
   schedule.
4. Observe one authorized real inbound message and verify one ledger row and the
   expected outbox cardinality.
5. Monitor intensively for 15 minutes, then for 60 minutes.

Rollback all services to the prior SHA if a message is lost, a `READY` event has
no outbox after five minutes, terminal states regress, lock timeouts/deadlocks
repeat, or p95 latency exceeds twice the baseline for ten minutes. Do not delete
ledger/outbox rows and do not replay dead letters as part of rollback.
