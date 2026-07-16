# DB-01 — Lifecycle and idempotency

- Migration `ai_agents.0004` adds the waiting state and model/prompt/policy
  version fields to `AgentRun`.
- Migration `webhooks.0005` adds a nullable unique provider-aware
  `deduplication_key` to raw webhook events.
- Existing rows remain valid because the new webhook key is nullable.
- Lifecycle event idempotency uses provider event ID, message ID, or a stable
  payload hash.
