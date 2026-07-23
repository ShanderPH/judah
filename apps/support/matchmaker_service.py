"""Canonical async entrypoints for the durable assignment protocol."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog
from django.conf import settings

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID, get_hubspot_client
from apps.support.conversation_cycle_service import CycleClassification, open_or_get_cycle
from apps.support.models import NewConversation
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_ATTACHABLE_CYCLE_CLASSIFICATIONS = (
    CycleClassification.CREATED,
    CycleClassification.DUPLICATE,
)


class AssignmentOutcome(StrEnum):
    """Result of processing one ready queue item."""

    ASSIGNED = "assigned"
    QUEUE_EMPTY = "queue_empty"
    NO_AGENT = "no_agent"
    LOCKED = "locked"
    STALE_TICKET = "stale_ticket"
    RETRYABLE_EXTERNAL_ERROR = "retryable_external_error"
    NON_RETRYABLE_EXTERNAL_ERROR = "non_retryable_external_error"


class QueueItemOutcome(StrEnum):
    """Typed terminal outcome for one queue selection."""

    ASSIGNED_NEW_EFFECT = "assigned_new_effect"
    CONVERGED_COMPLETED = "converged_completed"
    CONVERGED_EXTERNAL_OWNER = "converged_external_owner"
    QUARANTINED_LEGACY_AMBIGUOUS = "quarantined_legacy_ambiguous"
    QUARANTINED_STALE_CYCLE = "quarantined_stale_cycle"
    QUARANTINED_PERMANENT_PROVIDER_ERROR = "quarantined_permanent_provider_error"
    DEFERRED_NO_AGENT = "deferred_no_agent"
    DEFERRED_CANDIDATE_CHANGED = "deferred_candidate_changed"
    DEFERRED_PROVIDER_TRANSIENT = "deferred_provider_transient"
    CLAIMED_ELSEWHERE = "claimed_elsewhere"
    QUEUE_EMPTY = "queue_empty"
    SYSTEMIC_FAILURE = "systemic_failure"


@dataclass(frozen=True, slots=True)
class QueueItemResult:
    """PII-free result used by drains and aggregate telemetry."""

    outcome: QueueItemOutcome
    queue_row_id: uuid.UUID | None
    cycle_id: str | None
    made_progress: bool
    effect_applied: bool = False


def _active_queue():
    """Return post-rollout queue rows that have not been quarantined."""
    return NewConversation.objects.filter(
        automatic_assignment_eligible=True,
        queue_status__in=(
            NewConversation.QueueStatus.PENDING,
            NewConversation.QueueStatus.QUEUED,
        ),
    )


def process_queue_item(
    ticket_id: str | None = None,
    *,
    exclude_queue_row_ids: set[uuid.UUID] | None = None,
) -> QueueItemResult:
    """Process one distinct queue row and return an exhaustive result."""
    from apps.support.availability_runtime import log_runtime_rejection, may_assign
    from apps.support.durable_assignment_service import (
        execute_assignment_attempt,
        reserve_next_assignment,
    )

    if not may_assign():
        log_runtime_rejection("matchmaker_assign_next")
        return QueueItemResult(QueueItemOutcome.DEFERRED_NO_AGENT, None, None, False)
    reservation = reserve_next_assignment(ticket_id, exclude_queue_row_ids=exclude_queue_row_ids)
    row_id = reservation.queue_row_id
    cycle_id = str(reservation.cycle_id) if reservation.cycle_id else None
    if reservation.attempt is None:
        if reservation.reason == "queue_empty_or_claimed":
            return QueueItemResult(QueueItemOutcome.QUEUE_EMPTY, None, None, False)
        if reservation.reason == "legacy_cycle_ambiguous":
            return QueueItemResult(QueueItemOutcome.QUARANTINED_LEGACY_AMBIGUOUS, row_id, cycle_id, True)
        if reservation.reason == "skipped_stale_cycle":
            return QueueItemResult(QueueItemOutcome.QUARANTINED_STALE_CYCLE, row_id, cycle_id, True)
        if reservation.reason == "candidate_changed":
            return QueueItemResult(QueueItemOutcome.DEFERRED_CANDIDATE_CHANGED, row_id, cycle_id, False)
        return QueueItemResult(QueueItemOutcome.DEFERRED_NO_AGENT, row_id, cycle_id, False)
    if reservation.reason == "completed_same_cycle":
        return QueueItemResult(QueueItemOutcome.CONVERGED_COMPLETED, row_id, cycle_id, True)
    effect_pending = reservation.attempt.state == "reserved"
    outcome = execute_assignment_attempt(reservation.attempt.pk)
    mapping = {
        "assigned": QueueItemOutcome.ASSIGNED_NEW_EFFECT,
        "stale_ticket": QueueItemOutcome.QUARANTINED_PERMANENT_PROVIDER_ERROR,
        "skipped_stale_cycle": QueueItemOutcome.QUARANTINED_STALE_CYCLE,
        "retryable_external_error": QueueItemOutcome.DEFERRED_PROVIDER_TRANSIENT,
        "repair_required": QueueItemOutcome.SYSTEMIC_FAILURE,
    }
    typed = mapping.get(outcome, QueueItemOutcome.CLAIMED_ELSEWHERE)
    if outcome == "assigned" and not effect_pending:
        typed = QueueItemOutcome.CONVERGED_COMPLETED
    return QueueItemResult(
        typed,
        row_id,
        cycle_id,
        typed
        in {
            QueueItemOutcome.ASSIGNED_NEW_EFFECT,
            QueueItemOutcome.CONVERGED_COMPLETED,
            QueueItemOutcome.QUARANTINED_PERMANENT_PROVIDER_ERROR,
            QueueItemOutcome.QUARANTINED_STALE_CYCLE,
        },
        typed == QueueItemOutcome.ASSIGNED_NEW_EFFECT,
    )


def matchmaker_assign_next(ticket_id: str | None = None) -> AssignmentOutcome:
    """Compatibility facade for single-item callers."""
    result = process_queue_item(ticket_id)
    mapping = {
        QueueItemOutcome.ASSIGNED_NEW_EFFECT: AssignmentOutcome.ASSIGNED,
        QueueItemOutcome.CONVERGED_COMPLETED: AssignmentOutcome.ASSIGNED,
        QueueItemOutcome.QUEUE_EMPTY: AssignmentOutcome.QUEUE_EMPTY,
        QueueItemOutcome.DEFERRED_NO_AGENT: AssignmentOutcome.NO_AGENT,
        QueueItemOutcome.DEFERRED_CANDIDATE_CHANGED: AssignmentOutcome.NO_AGENT,
        QueueItemOutcome.QUARANTINED_STALE_CYCLE: AssignmentOutcome.STALE_TICKET,
        QueueItemOutcome.QUARANTINED_PERMANENT_PROVIDER_ERROR: AssignmentOutcome.STALE_TICKET,
        QueueItemOutcome.DEFERRED_PROVIDER_TRANSIENT: AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR,
        QueueItemOutcome.SYSTEMIC_FAILURE: AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR,
    }
    return mapping.get(result.outcome, AssignmentOutcome.LOCKED)


def matchmaker_drain_queue() -> dict:
    """Process ready conversations in FIFO order with a bounded loop."""
    from apps.support.availability_runtime import log_runtime_rejection, may_assign
    from apps.support.queue_service import get_eligible_agents

    if not may_assign():
        log_runtime_rejection("matchmaker_drain_queue")
        total_pending = _active_queue().count()
        return {
            "assigned": 0,
            "remaining": total_pending,
            "total_pending": total_pending,
            "quarantined": 0,
            "deferred": 0,
            "skipped_assignment_disabled": True,
        }

    total_pending = _active_queue().count()
    if total_pending == 0:
        return {
            "assigned": 0,
            "remaining": 0,
            "total_pending": 0,
            "quarantined": 0,
            "deferred": 0,
        }
    if not get_eligible_agents():
        return {
            "assigned": 0,
            "remaining": total_pending,
            "total_pending": total_pending,
            "quarantined": 0,
            "deferred": 0,
        }

    counts: dict[str, int] = {
        "assigned": 0,
        "converged": 0,
        "quarantined": 0,
        "deferred": 0,
        "claimed_elsewhere": 0,
        "systemic_failures": 0,
    }
    seen_queue_row_ids: set[uuid.UUID] = set()
    no_progress = 0
    while len(seen_queue_row_ids) < total_pending:
        result = process_queue_item(exclude_queue_row_ids=seen_queue_row_ids)
        if result.queue_row_id is not None:
            seen_queue_row_ids.add(result.queue_row_id)
        if result.outcome == QueueItemOutcome.QUEUE_EMPTY:
            break
        if result.outcome == QueueItemOutcome.SYSTEMIC_FAILURE:
            counts["systemic_failures"] += 1
            break
        if result.outcome == QueueItemOutcome.ASSIGNED_NEW_EFFECT:
            counts["assigned"] += 1
        elif result.outcome in {QueueItemOutcome.CONVERGED_COMPLETED, QueueItemOutcome.CONVERGED_EXTERNAL_OWNER}:
            counts["converged"] += 1
        elif result.outcome.value.startswith("quarantined_"):
            counts["quarantined"] += 1
        elif result.outcome.value.startswith("deferred_"):
            counts["deferred"] += 1
        elif result.outcome == QueueItemOutcome.CLAIMED_ELSEWHERE:
            counts["claimed_elsewhere"] += 1
        if not result.made_progress:
            no_progress += 1
            if result.queue_row_id is None:
                logger.warning("queue_drain_no_progress", outcome=result.outcome.value)
                break

    remaining = _active_queue().count()
    logger.info(
        "matchmaker_drain_done",
        total_pending=total_pending,
        **counts,
        remaining=remaining,
        processed=len(seen_queue_row_ids),
        no_progress=no_progress,
    )
    result: dict[str, Any] = {
        "remaining": remaining,
        "total_pending": total_pending,
        "processed": len(seen_queue_row_ids),
        "no_progress": no_progress,
        **counts,
    }
    if counts["assigned"] > total_pending:
        raise AssertionError("assigned cannot exceed total_pending")
    return result


def enqueue_new_ticket(
    hubspot_ticket_id: str,
    entered_at_ms: str | int | None = None,
    *,
    source_event_id: str = "",
) -> NewConversation | None:
    """Validate and idempotently enqueue one HubSpot ticket."""
    from apps.support.auto_assign_service import (
        _is_ticket_eligible,
        _parse_hubspot_timestamp,
    )
    from apps.support.availability_runtime import log_runtime_rejection, may_ingest_queue

    if not may_ingest_queue():
        log_runtime_rejection("enqueue_new_ticket")
        return None
    try:
        ticket_data = get_hubspot_client().get_ticket_details(hubspot_ticket_id)
    except ExternalServiceError:
        logger.error("matchmaker_hubspot_fetch_failed", ticket_id=hubspot_ticket_id)
        return None
    if not _is_ticket_eligible(ticket_data):
        return None

    # Gate B dual-write: attach a proven conversation cycle additively. With
    # CONVERSATION_CYCLES_ENFORCED off (default), a non-attachable admission
    # (missing timestamp/portal, stale, active conflict, repair) is telemetry
    # only and the legacy flow below is byte-for-byte unchanged. With
    # enforcement on, the same condition fails closed before any effect.
    confirmed_entered_at = entered_at_ms or ticket_data.get("entered_novo_at")
    cycle_result = open_or_get_cycle(
        hubspot_ticket_id=hubspot_ticket_id,
        entered_stage_value=confirmed_entered_at,
        source_event_id=source_event_id,
    )
    if cycle_result.admission.classification not in _ATTACHABLE_CYCLE_CLASSIFICATIONS:
        logger.warning(
            "conversation_cycle_admission_blocked",
            ticket_id=hubspot_ticket_id,
            classification=cycle_result.admission.classification.value,
            reason=cycle_result.admission.reason,
        )
        if settings.CONVERSATION_CYCLES_ENFORCED:
            return None

    entered_queue_at = _parse_hubspot_timestamp(confirmed_entered_at)
    if entered_queue_at is None:
        logger.warning(
            "conversation_cycle_identity_unavailable",
            ticket_id=hubspot_ticket_id,
            source_event_id=source_event_id,
        )
        return None
    new_conv, created = NewConversation.objects.get_or_create(
        hubspot_ticket_id=hubspot_ticket_id,
        defaults={
            "pipeline_id": ticket_data.get("pipeline", SUPPORT_PIPELINE_ID),
            "contact_name": ticket_data.get("contact_name") or "",
            "contact_email": ticket_data.get("contact_email") or "",
            "priority": ticket_data.get("priority") or "",
            "subject": ticket_data.get("subject") or "",
            "entered_queue_at": entered_queue_at,
            "automatic_assignment_eligible": True,
        },
    )
    if not created and new_conv.can_reactivate:
        new_conv.queue_status = NewConversation.QueueStatus.PENDING
        new_conv.automatic_assignment_eligible = True
        new_conv.assignment_attempts = 0
        new_conv.last_assignment_attempt_at = None
        new_conv.next_assignment_attempt_at = None
        new_conv.failure_code = ""
        new_conv.failure_message = ""
        new_conv.save(
            update_fields=[
                "queue_status",
                "automatic_assignment_eligible",
                "assignment_attempts",
                "last_assignment_attempt_at",
                "next_assignment_attempt_at",
                "failure_code",
                "failure_message",
                "updated_at",
            ]
        )
    if cycle_result.cycle is not None and new_conv.cycle_id != cycle_result.cycle.pk:
        new_conv.cycle = cycle_result.cycle
        new_conv.save(update_fields=["cycle", "updated_at"])
    return new_conv
