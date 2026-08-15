# N8N to JUDAH Coverage

This matrix records how every operational responsibility in
`Heimdall Agent - Triagem inteligente inChurch __ Hubspot.json` is owned after
the migration. The JSON remains a historical input only; it is not loaded or
called at runtime.

| N8N responsibility | Native backend owner | Result |
|---|---|---|
| Webhook intake and payload extraction | `apps.webhooks` HubSpot endpoint, schemas, persisted events | Replaced with signed, idempotent intake |
| Ticket, association, contact, thread, and message fetches | `apps.ai_agents.services.hubspot` | Replaced with bounded hydration and provider-error capture |
| Selecting the first associated contact | `apps.ai_agents.services.identity` | Removed; identity is evidence-based and ambiguous matches fail closed |
| Enriched AI prompt context | Typed `ConversationContext`, current-turn extraction, content safety | Replaced without persisting raw contact PII in identity metadata |
| Heimdall OpenAI Assistant node | `HeimdallTriageAgent` and typed `TriageDecision` | Replaced by native structured AI execution |
| Response parsing and fallback | Pydantic contracts, retry policy, confidence gates, human fallback | Replaced; invalid output cannot silently route |
| Menu choices | Native triage policy | Preserved as `1=suporte`, `2=dúvidas`, `3=boleto` |
| Business-hours, pauses, and holidays | Database-backed support calendar | Replaced; schedules are operational data instead of hard-coded dates |
| Quinta Fire and out-of-hours handling | Authoritative calendar plus Supervisor off-hours policy | Preserved through configurable schedules and safe human continuity |
| Channel router | HubSpot channel hydration and `channel_capabilities` | Replaced for email, webchat, and WhatsApp |
| Humanizer/wait and anti-duplicate delay | Customer-turn batching, Redis lock, lifecycle state, idempotency keys | Replaced without arbitrary workflow sleeps |
| Route reply subworkflow | `send_reply_with_audit` | Replaced with state permission, audit, and replay protection |
| Ticket route/stage subworkflow | Audited HubSpot stage tools and Matchmaker handoff | Replaced; assignment follows the backend queue rather than fixed owners |
| Email and CS/AC special branches | Existing ticket lifecycle, owner-change handling, and support pipeline | Retained under the backend's canonical routing authority |
| Tracking subworkflow | `AgentRun`, lifecycle events/transitions, tool audit, handoff observation | Replaced with durable local telemetry |

## Deliberate safety improvements

- Financial routes never execute automatically unless the active participant is
  `VERIFIED` from a delivery identifier matching a CRM contact.
- A unique ticket/contact association is only `PROBABLE`; multiple associations
  are never resolved by array order.
- Unknown, conflicting, or ambiguous identity receives one focused question per
  turn, for at most two attempts, then transfers to a human.
- Static owner IDs and expired hard-coded holiday windows from the JSON are not
  copied. The database schedule and Matchmaker are the current authorities.
- Replies and stage mutations are audited and idempotent, so HubSpot retries do
  not duplicate customer-visible effects.
