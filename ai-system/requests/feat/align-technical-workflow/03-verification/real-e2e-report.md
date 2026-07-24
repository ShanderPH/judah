# Real production E2E report

Date: 2026-07-16
Environment: Railway production services and isolated HubSpot test ticket
Trace: `CODEX-E2E-1784218268027`
HubSpot ticket: `46813120557` (archived after the test)

## Scope and safety

The test used the supplied credentials in memory only. No secret was copied to
the repository or printed in full. A synthetic HubSpot ticket was created with
an explicit `CODEX-E2E` prefix. After the workflow completed, the ticket was
archived and the lifecycle was closed. Final verification found no owner,
pending queue row, or assigned-conversation row for the test ticket.

## Result summary

| Stage | Result | Evidence |
| --- | --- | --- |
| Judah liveness | PASS | HTTP 200 |
| Judah readiness | PASS | database, cache, auth schema, and JWT mint all `ok` |
| Salomao health | PASS | HTTP 200 |
| Direct Salomao `/chat` | PASS | HTTP 200, 6.8 s, session preserved |
| Real Pinecone/OpenAI RAG | PARTIAL | agent completed in 12.1 s, but query returned zero Pinecone matches and requested escalation |
| HubSpot ticket creation | PASS | ticket created in AI triage pipeline/stage |
| Signed canonical webhook | PASS | HTTP 202, one event accepted and queued |
| Real HubSpot delivery | PASS | HubSpot later delivered its own property-change events |
| Webhook persistence/worker | PASS | persisted and processed with zero retries |
| Lifecycle routing | PASS | `RECEIVED` through `AI_SERVICE_RUNNING` |
| Heimdall triage | PASS | route `DUVIDAS_PLATAFORMA`, confidence 0.80 |
| Supervisor/SalomaoChat | PASS | response produced, confidence 0.86 |
| Knowledge use | PASS | agent trace reported RAG available and returned password-reset guidance |
| HubSpot thread reply | NOT TESTED | CRM ticket had no real Conversations thread; reply returned `no_incoming_message` |
| Safe fallback | PASS | lifecycle moved to human-handoff/queue state instead of silently dropping the response |
| Duplicate webhook | FAIL | repeated provider event returned HTTP 500 |
| Cleanup/closure | PASS | ticket archived, lifecycle `CLOSED`, no assignment created |

## Timeline

- `16:11:08Z`: synthetic HubSpot ticket created.
- `16:11:37Z`: signed webhook received.
- `16:11:37Z`: raw event persisted and normalized.
- `16:13:04Z`: AI worker began context/triage processing.
- `16:13:41Z`: Supervisor completed.
- `16:13:42Z`: audited HubSpot effects completed.
- `16:16:23Z`: cleanup close event processed; lifecycle reached `CLOSED`.

Observed queue delay before AI execution: approximately 86 seconds.
Supervisor execution latency: 34.63 seconds.
Tokens: 3,070 prompt + 276 completion = 3,346.

## Supervisor output

The real pipeline classified the request as a platform question about password
reset, with medium priority and neutral sentiment. It generated concrete
password-reset instructions and did not initially request human handoff.

Because the synthetic CRM ticket had no HubSpot Conversations thread, the
audited `send_thread_reply` operation failed with `no_incoming_message`. The
workflow then failed safely into human handoff instead of claiming delivery.

## Findings

### P1 — duplicate provider events return HTTP 500

Posting the exact same signed HubSpot event a second time returned an internal
server error. Production still has a unique constraint on
`webhook_events.event_id`, while the deployed persistence path attempts another
insert. HubSpot retries are normal, so the receiver must return an idempotent
202 rather than 500.

The local branch contains provider-aware deduplication using
`deduplication_key`, but production does not have that column or the
`webhooks.0005_webhookevent_deduplication_key` migration applied.

### P1 — deployed schema/code differs from the local aligned branch

Production `agent_runs` does not contain the local branch fields
`model_name`, `prompt_version`, and `policy_version`. The database records a
different historical AI migration, while the current local migration has not
been applied. The local workflow changes therefore have not yet been fully
deployed and must pass a migration-aware rollout.

### P2 — AI queue delay

The task waited about 86 seconds before the AI worker began processing. The
workflow remained durable, but this is high for a chat experience and suggests
worker availability, queue backlog, or routing latency should be monitored.

### P2 — RAG and source metadata

The standalone real RAG probe returned zero matches for the password-reset
query and escalated. During the full Supervisor run, useful guidance was
produced, but the response cited an article named `Sem título` while the
structured `sources` list was empty. Knowledge metadata and citation
consistency need review.

### P2 — cost tracking

The run persisted 3,346 tokens but `total_cost_usd` was `0.000000`, indicating
that pricing for the reported `gpt-5.5` model is not mapped in the deployed
cost tracker.

## Cleanup evidence

- HubSpot ticket archived: yes.
- HubSpot owner assigned: no.
- `new_conversations` row: 0.
- `assigned_conversations` row: 0.
- Final conversation state: `CLOSED`.
- Lifecycle failure count: 0.

## Recommended next actions

1. Deploy the local webhook deduplication change and apply its migration before
   repeating provider retry tests.
2. Reconcile and apply the AI-agent migration against the production schema.
3. Confirm an `ai_tasks` worker is continuously consuming the queue and add
   queue-age monitoring.
4. Repeat the E2E using a dedicated HubSpot sandbox Conversations thread to
   verify the final outgoing reply without involving real support agents.
5. Fix RAG article titles/source propagation and add pricing for the deployed
   model identifier.
