# Native Heimdall Backend — Scope

## Objective

Replace the operational N8N Heimdall workflow with the existing JUDAH backend as the single workflow authority, preserving HubSpot behavior while adding deterministic customer identity resolution, typed triage, lifecycle safety, idempotent effects, auditability, retries, and human fallback.

## Source workflow behavior to preserve

- HubSpot ticket and conversation hydration.
- Channel-aware handling for email, webchat, and WhatsApp.
- Heimdall routes: `BOLETO`, `EVENTOS`, `DUVIDAS_PLATAFORMA`, `MEIOS_DE_PAGAMENTO`, `FINANCEIRO`, `SUPORTE_TECNICO_N1`, `CUSTOMER_SUCCESS`, `ESCALAR_IMEDIATAMENTE`, and `ATENDIMENTO_IA`.
- Business-hours context, including Quinta Fire and exceptional schedules.
- Customer-visible replies, ticket routing, human handoff, and tracking.

## Confirmed backend foundation

- Canonical `/api/v1/webhooks/hubspot/` ingress with HMAC validation and persisted idempotency.
- `ConversationInstance` lifecycle and append-only event/transition ledgers.
- Typed Heimdall output and deterministic Supervisor execution.
- HubSpot context hydration, reply sending, ticket routing, audit logs, retries, watchdog, and Matchmaker handoff.

## Gaps addressed by this request

- Contact lifecycle states exist but no customer identity resolver is connected to runtime.
- Associated contacts are treated as identity without validating the active conversation participant.
- Contact profiles and identity confidence are absent from agent handoffs.
- Ambiguous or missing identity has no focused collection loop.
- Sensitive routes do not require a stronger identity level.
- Heimdall menu mapping differs from the N8N menu contract.
- Confidence thresholds are not consistently enforced by the production Supervisor.
- AI dispatch is unnecessarily coupled to the external Salomao v1 URL even though Heimdall is native.
- Business-hours dispatch does not consistently use the database-backed schedule.

## Safety constraints

- No secrets or raw PII in logs/audit snapshots.
- No automatic destructive or financial action for unverified identities.
- No duplicate reply or HubSpot mutation for replayed webhooks.
- Any invalid AI contract, identity conflict, unsupported channel, or exhausted retry budget fails to human support.
