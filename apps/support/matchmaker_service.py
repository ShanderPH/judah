"""Canonical async entrypoints for the durable assignment protocol."""

from __future__ import annotations

from enum import StrEnum

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


def _active_queue():
    """Return post-rollout queue rows that have not been quarantined."""
    return NewConversation.objects.filter(
        automatic_assignment_eligible=True,
        queue_status__in=(
            NewConversation.QueueStatus.PENDING,
            NewConversation.QueueStatus.QUEUED,
        ),
    )


def matchmaker_assign_next(ticket_id: str | None = None) -> AssignmentOutcome:
    """Reserve and converge the requested or oldest ready queue row."""
    from apps.support.availability_runtime import log_runtime_rejection, may_assign
    from apps.support.durable_assignment_service import (
        execute_assignment_attempt,
        reserve_next_assignment,
    )

    if not may_assign():
        log_runtime_rejection("matchmaker_assign_next")
        return AssignmentOutcome.NO_AGENT
    reservation = reserve_next_assignment(ticket_id)
    if reservation.attempt is None:
        if reservation.reason == "queue_empty_or_claimed":
            return AssignmentOutcome.QUEUE_EMPTY
        return AssignmentOutcome.NO_AGENT
    if reservation.reason == "completed":
        return AssignmentOutcome.ASSIGNED
    outcome = execute_assignment_attempt(reservation.attempt.pk)
    try:
        return AssignmentOutcome(outcome)
    except ValueError:
        if outcome == "repair_required":
            return AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR
        return AssignmentOutcome.LOCKED


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

    assigned = 0
    processed = 0
    quarantined = 0
    deferred = 0
    while processed < total_pending + 5:
        outcome = matchmaker_assign_next()
        if outcome == AssignmentOutcome.ASSIGNED:
            assigned += 1
            processed += 1
            continue
        if outcome == AssignmentOutcome.STALE_TICKET:
            quarantined += 1
            processed += 1
            continue
        if outcome in (
            AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR,
            AssignmentOutcome.NON_RETRYABLE_EXTERNAL_ERROR,
        ):
            deferred += 1
        break

    remaining = _active_queue().count()
    logger.info(
        "matchmaker_drain_done",
        total_pending=total_pending,
        assigned=assigned,
        remaining=remaining,
        quarantined=quarantined,
        deferred=deferred,
    )
    return {
        "assigned": assigned,
        "remaining": remaining,
        "total_pending": total_pending,
        "quarantined": quarantined,
        "deferred": deferred,
    }


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
