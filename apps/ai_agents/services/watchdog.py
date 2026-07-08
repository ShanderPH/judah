"""Watchdog utilities for stuck conversation lifecycle instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.lifecycle import TERMINAL_STATES, LifecycleEngine

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
        timeout = _timeout_for_state(instance.state)
        instance.failure_count += 1
        instance.current_error = f"Lifecycle watchdog timeout in state {instance.state} after {timeout}."
        instance.next_retry_at = timezone.now() + timedelta(minutes=5)
        instance.save(update_fields=["failure_count", "current_error", "next_retry_at", "updated_at"])

        if instance.failure_count >= max_failures:
            if instance.state != ConversationInstance.State.FAILED_RETRYABLE:
                engine.transition(
                    instance,
                    ConversationInstance.State.FAILED_RETRYABLE,
                    reason="Lifecycle watchdog prepared terminal failure.",
                )
            engine.transition(
                instance,
                ConversationInstance.State.FAILED_TERMINAL,
                reason="Lifecycle watchdog marked terminal failure.",
            )
            marked_terminal += 1
        else:
            engine.transition(
                instance,
                ConversationInstance.State.FAILED_RETRYABLE,
                reason="Lifecycle watchdog marked retryable failure.",
            )
            marked_retryable += 1

    return WatchdogResult(
        scanned=scanned,
        marked_retryable=marked_retryable,
        marked_terminal=marked_terminal,
    )


__all__ = ["WatchdogResult", "run_lifecycle_watchdog", "stuck_instances"]
