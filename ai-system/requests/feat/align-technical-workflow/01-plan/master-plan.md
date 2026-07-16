# Master Plan

## Goal

Make the backend the authority for conversation state, deterministic routing,
agent execution, external effects, retries, and human handoff.

## Technical approach

1. Add `WAITING_FOR_CUSTOMER` and valid resume/confirmation transitions.
2. Extend triage and supervisor contracts with confidence, evidence, policy
   version, and the document-defined supervisor outcomes.
3. Make webhook lifecycle decisions control dispatch and skip duplicate effects.
4. Run Heimdall deterministically, route missing data and risk before service
   execution, and expose a structured `SupervisorDecision`.
5. Apply replies and handoffs in a backend execution layer that enforces state
   permissions, idempotency, and `ToolCallAuditLog`.
6. Persist `AgentRun` records for triage, specialized service, and supervisor
   decisions.
7. Queue AI-to-human transfers through Matchmaker and advance human lifecycle
   states when assignment and closure occur.
8. Add bounded retries for webhook and AI tasks, schedule the watchdog, and
   re-dispatch retryable lifecycle instances.
9. Correct HubSpot v3 signature validation and timestamp replay protection.
10. Cover missing-data, waiting, confirmation, handoff, audit, routing, retry,
    and signature paths with tests.

## Acceptance criteria

- Duplicate events do not repeat dispatch or external effects.
- Incoming AI events advance through hydration, triage, service, and waiting.
- Missing data produces a focused question and `WAITING_FOR_CUSTOMER`.
- Candidate resolution waits for deterministic customer confirmation.
- Critical, low-confidence, unsupported, or failed cases enter human queue with
  a persisted handoff package.
- Agent and tool executions are correlated to a conversation instance.
- Retryable failures are scheduled and exhausted failures safely hand off.
- HubSpot v3 signatures use the official request ordering, Base64 digest, and
  five-minute timestamp window.
- Ruff, Django checks, migrations, and the complete local test suite pass.
