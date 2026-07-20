# BE-09 / OPS-08 — queue-safe runtime capabilities

Implemented:

- `may_ingest_queue` persists authoritative webhook intake independently of
  the assignment switch;
- `may_reconcile_queue` repairs the NOVO-stage backlog while assignment is off;
- `may_assign` requires runtime authority, the explicit assignment switch, and
  safe eligibility whenever shadow or canary controls are active;
- `AUTO_ASSIGNMENT_ENABLED` now defaults to `false`; test and development
  behavior is explicit in their environment settings;
- `AUTO_ASSIGNMENT_CANARY_AGENT_IDS` filters automatic candidates by local
  `Agent.id` UUID and cannot run over legacy eligibility;
- webhook, compatibility, single-ticket, drain, and reconciliation entrypoints
  use their matching capability.

The assignment-disabled path creates or reuses one queue row and stops before
the forced SAT refresh or HubSpot owner mutation. Enabling assignment later
drains the preserved backlog. Railway pre-deploy migrations also preserve the
queue instead of quarantining pending rows.
