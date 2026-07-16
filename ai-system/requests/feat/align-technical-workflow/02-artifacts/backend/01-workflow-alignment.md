# BE-01 — Workflow alignment

- The canonical webhook records and normalizes events before selecting one
  deterministic route.
- Heimdall and the Supervisor return typed decisions; agents do not mutate the
  lifecycle or execute external effects directly.
- Missing data and candidate resolutions enter `WAITING_FOR_CUSTOMER`.
- OUTGOING events are logged without terminalizing an active AI conversation;
  the first human reply advances `HUMAN_ASSIGNED` to `HUMAN_IN_PROGRESS`.
- Explicit confirmation is required before `RESOLVED_BY_AI` and `CLOSED`.
- Replies and handoffs are applied by an audited, idempotent execution layer.
- Unsupported, risky, low-confidence, adversarial, and exhausted cases use a
  persisted human handoff package and Matchmaker.
