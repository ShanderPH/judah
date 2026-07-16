# Current Gap Analysis

## Goal

Align the executable JUDAH workflow with the attached Heimdall technical
workflow summary while preserving the stable Matchmaker/SAT support flow.

## Confirmed gaps

- The lifecycle router records a decision but does not control dispatch.
- `WAITING_FOR_CUSTOMER` is absent and successful AI replies close immediately.
- `SupervisorDecision`, `AgentRun`, `ToolCallAuditLog`, state tool permissions,
  and the handoff package are not connected to runtime effects.
- Missing triage data does not enter a deterministic collection loop.
- AI tasks swallow failures and do not use bounded Celery retries.
- The watchdog is available only as a management command and no retry consumer
  processes `next_retry_at`.
- Human handoff does not enqueue the conversation through Matchmaker.
- HubSpot v3 validation does not follow the current Base64/timestamp contract.
- Conversation event processing status is not finalized after dispatch.

## Compatibility constraints

- Keep `/api/v1/webhooks/hubspot/` as the canonical endpoint.
- Preserve existing public API response fields.
- Preserve support ticket assignment, SAT, and closure behavior.
- Avoid real external calls in automated tests.
- Keep `AI_ROUTING_ENABLED` as the rollout switch, with human fallback when AI
  routing is unavailable.
