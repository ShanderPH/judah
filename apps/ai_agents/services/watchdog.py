"""Watchdog utilities for stuck conversation lifecycle instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
from asgiref.sync import async_to_sync
from django.db.models import Q
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.channel_capabilities import normalize_channel
from apps.ai_agents.services.conversation_turn import current_incoming_turn, incoming_message_id
from apps.ai_agents.services.instance_identity import supersede_placeholder_if_canonical_exists
from apps.ai_agents.services.lifecycle import (
    TERMINAL_STATES,
    LifecycleEngine,
    NormalizedEvent,
    RouteDecision,
)

logger = structlog.get_logger(__name__)

DEFAULT_STATE_TIMEOUT_MINUTES: dict[str, int] = {
    ConversationInstance.State.CONTEXT_HYDRATING: 10,
    ConversationInstance.State.TRIAGE_RUNNING: 10,
    ConversationInstance.State.AI_SERVICE_RUNNING: 15,
    ConversationInstance.State.QUEUE_PENDING: 240,
    ConversationInstance.State.FAILED_RETRYABLE: 60,
}


@dataclass(frozen=True)
class WatchdogResult:
    """Summary returned by the lifecycle watchdog."""

    scanned: int
    marked_retryable: int
    marked_terminal: int


@dataclass(frozen=True)
class WaitingMessageReconciliationResult:
    """Summary of message-ID reconciliation for waiting conversations."""

    scanned: int
    recovered: int
    unchanged: int
    ineligible: int
    failed: int


def _timeout_for_state(state: str) -> timedelta | None:
    minutes = DEFAULT_STATE_TIMEOUT_MINUTES.get(state)
    if minutes is None:
        return None
    return timedelta(minutes=minutes)


def stuck_instances(limit: int = 100):
    """Return instances that exceeded their configured state timeout."""
    now = timezone.now()
    query = Q()
    for state, minutes in DEFAULT_STATE_TIMEOUT_MINUTES.items():
        query |= Q(state=state, last_activity_at__lt=now - timedelta(minutes=minutes))
    return (
        ConversationInstance.objects.filter(query)
        .exclude(state__in=TERMINAL_STATES)
        .order_by("last_activity_at", "created_at")[:limit]
    )


def run_lifecycle_watchdog(*, limit: int = 100, max_failures: int = 3) -> WatchdogResult:
    """Mark stuck active instances as retryable or terminal failures."""
    engine = LifecycleEngine()
    scanned = 0
    marked_retryable = 0
    marked_terminal = 0

    for instance in stuck_instances(limit=limit):
        scanned += 1
        canonical = supersede_placeholder_if_canonical_exists(instance)
        if canonical is not None:
            marked_terminal += 1
            continue

        timeout = _timeout_for_state(instance.state)
        instance.failure_count += 1
        instance.current_error = f"Lifecycle watchdog timeout in state {instance.state} after {timeout}."
        exhausted = instance.failure_count >= max(1, max_failures)
        instance.next_retry_at = None if exhausted else timezone.now() + timedelta(minutes=5)
        instance.save(update_fields=["failure_count", "current_error", "next_retry_at", "updated_at"])

        if instance.state != ConversationInstance.State.FAILED_RETRYABLE:
            engine.transition(
                instance,
                ConversationInstance.State.FAILED_RETRYABLE,
                reason="Lifecycle watchdog marked retryable failure.",
            )
        if exhausted:
            missing_identity = not instance.hubspot_thread_id
            engine.transition(
                instance,
                ConversationInstance.State.FAILED_TERMINAL,
                reason=(
                    "Lifecycle watchdog exhausted retries without a canonical thread; automatic handoff is unsafe."
                    if missing_identity
                    else "Lifecycle watchdog exhausted the bounded retry budget."
                ),
                actor_type="lifecycle_watchdog",
            )
            marked_terminal += 1
        else:
            marked_retryable += 1

    return WatchdogResult(
        scanned=scanned,
        marked_retryable=marked_retryable,
        marked_terminal=marked_terminal,
    )


def waiting_customer_instances(limit: int = 25) -> list[ConversationInstance]:
    """Select a bounded mix of live and long-waiting conversations.

    Half of every batch prioritizes recent customer activity. The other half
    uses ``updated_at`` as a rotation cursor because each reconciliation check
    updates it. This prevents a permanently busy recent pool from starving
    older waiting threads.
    """
    bounded_limit = max(1, limit)
    queryset = ConversationInstance.objects.filter(
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        hubspot_thread_id__isnull=False,
    ).exclude(hubspot_thread_id="")
    recent_limit = (bounded_limit + 1) // 2
    recent = list(queryset.order_by("-last_activity_at", "-created_at")[:recent_limit])
    recent_ids = [instance.pk for instance in recent]
    rotating = list(
        queryset.exclude(pk__in=recent_ids).order_by("updated_at", "created_at")[: bounded_limit - len(recent)]
    )
    return [*recent, *rotating]


def waiting_customer_backlog_size() -> int:
    """Return the number of concrete conversations covered by reconciliation."""
    return (
        ConversationInstance.objects.filter(
            state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
            hubspot_thread_id__isnull=False,
        )
        .exclude(hubspot_thread_id="")
        .count()
    )


def _record_reconciliation_check(
    instance: ConversationInstance,
    *,
    outcome: str,
    observed_message_id: str = "",
) -> bool:
    """Persist a PII-free reconciliation checkpoint for fair batch rotation."""
    try:
        instance.refresh_from_db()
        metadata = dict(instance.metadata or {})
        metadata.update(
            {
                "waiting_message_reconciled_at": timezone.now().isoformat(),
                "waiting_message_reconciliation": {
                    "outcome": outcome,
                    "observed_message_id": observed_message_id,
                },
            }
        )
        instance.metadata = metadata
        instance.save(update_fields=["metadata", "updated_at"])
    except Exception as exc:
        # A diagnostic checkpoint must never abort recovery of the remaining
        # bounded batch or mask the original provider/lifecycle error.
        logger.warning(
            "waiting_customer_reconciliation_checkpoint_failed",
            conversation_instance_id=str(instance.pk),
            error_type=type(exc).__name__,
            error=str(exc),
            action="continue_without_checkpoint",
        )
        return False
    return True


def reconcile_waiting_customer_messages(*, limit: int = 25) -> WaitingMessageReconciliationResult:
    """Recover incoming HubSpot messages missed by calculated-property webhooks.

    ``conversation.newMessage`` is the primary trigger. This bounded poller is
    the safety net: it compares the provider message ID with the last customer
    turn persisted by Judah, records a synthetic idempotent lifecycle event,
    and schedules the same thread pipeline used by the real webhook.
    """
    from apps.ai_agents.services.hubspot import (
        evaluate_salomao_ticket_eligibility,
        hydrate_thread_context,
    )
    from apps.ai_agents.tasks import schedule_salomao_thread_customer_turn

    scanned = 0
    recovered = 0
    unchanged = 0
    ineligible = 0
    failed = 0

    for instance in waiting_customer_instances(limit=limit):
        scanned += 1
        thread_id = str(instance.hubspot_thread_id or "")
        try:
            context = async_to_sync(hydrate_thread_context)(
                thread_id,
                ticket_id=instance.hubspot_ticket_id,
            )
            if context.get("errors") and not context.get("conversation_history"):
                failed += 1
                _record_reconciliation_check(instance, outcome="provider_context_unavailable")
                logger.warning(
                    "waiting_customer_message_reconciliation_failed",
                    conversation_instance_id=str(instance.pk),
                    thread_id=thread_id,
                    ticket_id=instance.hubspot_ticket_id,
                    errors=context.get("errors"),
                    action="retry_on_next_reconciliation_cycle",
                )
                continue

            eligibility = evaluate_salomao_ticket_eligibility(context)
            if not eligibility["eligible"]:
                ineligible += 1
                _record_reconciliation_check(
                    instance,
                    outcome=f"ineligible:{eligibility['reason']}",
                )
                logger.info(
                    "waiting_customer_message_reconciliation_ineligible",
                    conversation_instance_id=str(instance.pk),
                    thread_id=thread_id,
                    ticket_id=instance.hubspot_ticket_id,
                    reason=eligibility["reason"],
                    retryable=eligibility["retryable"],
                    action="safe_noop",
                )
                continue

            current_turn = current_incoming_turn(context)
            if not current_turn:
                unchanged += 1
                _record_reconciliation_check(instance, outcome="no_current_incoming_turn")
                continue

            message_id = incoming_message_id(current_turn[-1])
            instance.refresh_from_db()
            if instance.state != ConversationInstance.State.WAITING_FOR_CUSTOMER:
                unchanged += 1
                _record_reconciliation_check(instance, outcome="state_changed_during_reconciliation")
                continue
            if message_id == instance.last_message_id:
                unchanged += 1
                _record_reconciliation_check(
                    instance,
                    outcome="customer_turn_already_persisted",
                    observed_message_id=message_id,
                )
                continue

            payload = {
                "threadId": thread_id,
                "messageId": message_id,
                "direction": "INCOMING",
                "detectedBy": "waiting_customer_reconciliation",
            }
            event = NormalizedEvent(
                source="hubspot_reconciliation",
                source_event_id=f"reconciled:{message_id}",
                event_type="conversation_message_received",
                idempotency_key=f"reconciled-message:v1:{thread_id}:{message_id}",
                payload=payload,
                hubspot_thread_id=thread_id,
                hubspot_ticket_id=str(context.get("ticket_id") or instance.hubspot_ticket_id or "") or None,
                hubspot_contact_id=str((context.get("contact_ids") or [""])[0]) or None,
                channel=normalize_channel(context.get("originating_channel")),
                direction="INCOMING",
                pipeline_id=str(context.get("pipeline") or "") or None,
                pipeline_stage_id=str(context.get("pipeline_stage") or "") or None,
                message_id=message_id,
            )
            record = LifecycleEngine().record_normalized_event(
                event,
                decision=RouteDecision(
                    route="AI_TRIAGE",
                    target_state=ConversationInstance.State.CONTEXT_HYDRATING,
                    reason="Reconciliation found an unprocessed incoming HubSpot message.",
                    can_send_reply=True,
                ),
            )
            _record_reconciliation_check(
                record.instance,
                outcome="customer_turn_recovered" if record.event_created else "customer_turn_already_recorded",
                observed_message_id=message_id,
            )
            if record.event_created:
                schedule_salomao_thread_customer_turn(thread_id)
                recovered += 1
                logger.warning(
                    "waiting_customer_message_recovered",
                    conversation_instance_id=str(record.instance.pk),
                    thread_id=thread_id,
                    ticket_id=record.instance.hubspot_ticket_id,
                    message_id=message_id,
                    action="schedule_thread_supervisor",
                )
            else:
                unchanged += 1
        except Exception as exc:
            failed += 1
            _record_reconciliation_check(instance, outcome=f"error:{type(exc).__name__}")
            logger.exception(
                "waiting_customer_message_reconciliation_error",
                conversation_instance_id=str(instance.pk),
                thread_id=thread_id,
                ticket_id=instance.hubspot_ticket_id,
                error_type=type(exc).__name__,
                error=str(exc),
                action="continue_bounded_batch",
            )

    return WaitingMessageReconciliationResult(
        scanned=scanned,
        recovered=recovered,
        unchanged=unchanged,
        ineligible=ineligible,
        failed=failed,
    )


__all__ = [
    "WaitingMessageReconciliationResult",
    "WatchdogResult",
    "reconcile_waiting_customer_messages",
    "run_lifecycle_watchdog",
    "stuck_instances",
    "waiting_customer_backlog_size",
    "waiting_customer_instances",
]
