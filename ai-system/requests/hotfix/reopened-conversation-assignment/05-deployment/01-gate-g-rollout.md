# Gate G rollout record

**Request:** `hotfix/reopened-conversation-assignment`
**Authorization:** implementation of Gate G on 21 July 2026
**External mutations executed:** none

## Scope

- Expose a PII-free cycle rollout posture in assignment and platform readiness.
- Detect legacy rows, projection mismatches, queued cycles without dispatch and
  unsafe enforcement explicitly.
- Document expand/migrate/contract stop conditions, observation and rollback.

Deploys, shared-database migrations/backfills, Railway variable changes,
canary, general enforcement, HubSpot writes and incident-ticket repairs remain
separate execution approvals under section 10 of the master plan.

## Sequence and stop conditions

| Mark | Action | Required evidence | Stop condition |
|---|---|---|---|
| G1 | Deploy additive schema/code with enforcement off | API, Worker and Beat on the same release; health reachable | migration or service unhealthy |
| G2 | Inspect readiness | portal configured; no mismatch; expected legacy counts | any mismatch or missing dispatch |
| G3 | Backfill authorized staging clone | dry-run reviewed; quarantine disposition; idempotent rerun | ambiguity not approved |
| G4 | Deploy cycle-aware contract and drain old workers | no legacy writer growth; queues stable | legacy count grows |
| G5 | Canary | zero duplicate active cycles; repair age within SLA | invariant, owner or capacity divergence |
| G6 | General enforcement | `enforcement_ready=true`; explicit approval | any readiness reason |
| G7 | Late contract | stable window and zero nullable writer coverage | mixed-version writer present |

No mark implies authorization for the next one.

## Read-only evidence commands

```powershell
railway.cmd status --json
railway.cmd deployment list --environment staging --json
railway.cmd logs --environment staging --service API
railway.cmd logs --environment staging --service Worker
railway.cmd logs --environment staging --service Beat
```

Inspect `GET /api/v1/health/ready` and
`GET /api/v1/support/queue/health/`. The conversation-cycle section must never
contain portal IDs, ticket IDs, owner IDs, names, emails or cycle keys.

## Rollback

If an integrity or external-owner divergence appears, disable cycle enforcement.
If effects continue or integrity is at risk, disable automatic assignment as
the emergency containment step. Keep migrations, cycles, ingestion and repair
evidence in place. Do not reverse migration `0023` after multi-cycle history
exists and do not mutate HubSpot or production rows without approval.
