# Master Plan — Native Heimdall Backend

## Approved outcome

JUDAH becomes the single backend authority for HubSpot intake, customer identity, Heimdall triage, Salomão service, HubSpot effects, lifecycle, tracking, and human handoff. N8N is no longer required for this workflow.

## Work packages

### BE-01 — Customer identity contract and resolver

- Add a provider-neutral typed identity contract.
- Hydrate bounded HubSpot contact profiles.
- Match thread participant delivery identifiers against normalized contact email/phone values.
- Distinguish `VERIFIED`, `PROBABLE`, `AMBIGUOUS`, `UNKNOWN`, and `CONFLICT`.
- Persist only safe identity evidence and operational metadata.

Acceptance:

- Multiple contacts are never resolved by list order.
- A unique matching delivery identifier is verified.
- A unique association without participant proof is only probable.
- Missing, ambiguous, and conflicting cases produce deterministic outcomes.

### BE-02 — Identity collection and sensitive-route gate

- Connect `CONTACT_REQUIRED` and `CONTACT_COLLECTING` to runtime.
- Ask one focused question without exposing complete PII.
- Resume on the next incoming customer turn.
- Cap attempts and fall back to human support.
- Require verified identity for financial and other sensitive routes.

Acceptance:

- One customer turn receives at most one identity prompt.
- Duplicate events cannot repeat the prompt.
- Sensitive routes cannot execute with insufficient identity.

### BE-03 — Heimdall policy migration

- Preserve the N8N route taxonomy in the typed backend contract.
- Correct menu mapping to `1=support`, `2=platform questions`, `3=billing copy`.
- Enforce configurable minimum and automatic-routing confidence thresholds.
- Preserve explicit-human, critical, aggression, and prompt-injection overrides.
- Include identity and bidirectional recent conversation context without exposing unnecessary PII.

Acceptance:

- Invalid output fails safely.
- Low confidence is never silently auto-routed.
- Critical and explicit-human requests always hand off.

### BE-04 — Native dispatch, schedules, effects, and audit

- Remove the dispatcher dependency on `SALOMAO_V1_BASE_URL`; native Heimdall must run whenever AI routing is enabled.
- Use the database-backed support schedule for synchronous dispatch decisions.
- Keep Redis batching/locks, tool idempotency, Celery retry, watchdog, HubSpot audit, and Matchmaker handoff.
- Preserve Salomão v1 as an optional specialist member, with safe human fallback when unavailable.

Acceptance:

- Native triage dispatches with no N8N and no external Salomão URL.
- Replayed webhook events do not duplicate effects.
- Off-hours behavior is derived from the authoritative schedule.

### V-01 — Verification and documentation

- Unit-test identity matching, ambiguity, conflict, PII masking, attempt limits, menu mapping, confidence policy, and native dispatch.
- Run focused AI/webhook suites, lint, type checks, migration checks, and broader regression tests.
- Document runtime flow, settings, rollout, and rollback.

## Rollout

1. Deploy migrations and code with `AI_ROUTING_ENABLED=false`.
2. Enable shadow/audit validation in staging with mock external calls.
3. Enable a deterministic percentage rollout.
4. Observe identity resolution, route confidence, handoff, duplicate suppression, retries, and provider errors.
5. Increase rollout only when stop gates remain healthy.

## Stop gates

- Any false verified identity.
- Any duplicate customer reply or repeated ticket mutation.
- Any sensitive action without verified identity.
- Any critical request not handed to a human.
- Any material regression in Matchmaker, SAT, ticket closure, or existing customer-message batching.
