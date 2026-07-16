"""Matchmaker — async assignment orchestration for the auto-assignment queue.

The Matchmaker decouples webhook ingestion from assignment execution.
Instead of processing assignments synchronously within the webhook request,
tickets are enqueued in ``new_conversations`` and the Matchmaker picks them
up via Celery tasks.

Concurrency is protected by:
  - ``select_for_update(skip_locked=True)`` on ``NewConversation`` rows,
    ensuring two workers never grab the same ticket.
  - Redis-based locks on drain operations to prevent overlapping drains.

The 4-rule priority algorithm in ``queue_service.py`` is reused as-is.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

import structlog
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID, get_hubspot_client
from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotResourceNotFoundError
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentLog,
    NewConversation,
)
from apps.support.queue_service import (
    get_last_assigned_owner_id,
    increment_agent_chat_count,
    select_next_agent,
)
from apps.support.sat_service import sat_reconcile_agent_load
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)


class AssignmentOutcome(StrEnum):
    """Result of processing one ready queue item."""

    ASSIGNED = "assigned"
    QUEUE_EMPTY = "queue_empty"
    NO_AGENT = "no_agent"
    LOCKED = "locked"
    STALE_TICKET = "stale_ticket"
    RETRYABLE_EXTERNAL_ERROR = "retryable_external_error"
    NON_RETRYABLE_EXTERNAL_ERROR = "non_retryable_external_error"


def _transition_assigned_lifecycle(hubspot_ticket_id: str, agent: Agent) -> None:
    """Advance the deterministic lifecycle after Matchmaker assignment."""
    try:
        from apps.ai_agents.models import ConversationInstance
        from apps.ai_agents.services.lifecycle import InvalidStateTransitionError, LifecycleEngine

        engine = LifecycleEngine()
        instance = ConversationInstance.objects.filter(hubspot_ticket_id=str(hubspot_ticket_id)).first()
        if instance is None:
            return
        instance.assigned_agent_id = str(agent.hubspot_owner_id)
        instance.save(update_fields=["assigned_agent_id", "updated_at"])
        try:
            engine.transition(
                instance,
                ConversationInstance.State.HUMAN_ASSIGNED,
                reason="Matchmaker assigned the conversation to a human agent.",
                actor_type="matchmaker",
                actor_id=str(agent.hubspot_owner_id),
            )
        except InvalidStateTransitionError as exc:
            logger.info(
                "matchmaker_lifecycle_transition_skipped",
                ticket_id=hubspot_ticket_id,
                error=str(exc),
            )
    except Exception as exc:
        logger.warning(
            "matchmaker_lifecycle_transition_failed",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
        )


def _active_queue():
    """Return queue rows that have not been quarantined."""
    return NewConversation.objects.filter(
        queue_status__in=(NewConversation.QueueStatus.PENDING, NewConversation.QueueStatus.QUEUED)
    )


def _ready_queue():
    """Return active rows whose retry backoff has elapsed."""
    now = timezone.now()
    return _active_queue().filter(Q(next_assignment_attempt_at__isnull=True) | Q(next_assignment_attempt_at__lte=now))


def matchmaker_assign_next() -> AssignmentOutcome:
    """Attempt to assign the oldest pending NewConversation to the best agent.

    Uses a Redis lock per ticket to prevent two workers from processing the
    same ticket simultaneously.  Before assignment, reconciles the candidate
    agent's load with HubSpot via the SAT service.

    Returns:
        Structured outcome describing whether to continue draining the queue.
    """
    from django.core.cache import cache

    # Pick the oldest pending conversation using select_for_update
    with transaction.atomic():
        new_conv = _ready_queue().select_for_update(skip_locked=True).order_by("entered_queue_at").first()
        if new_conv is None:
            return AssignmentOutcome.QUEUE_EMPTY

        # Claim this ticket with a Redis lock to prevent double-processing
        # after the DB lock is released
        claim_key = f"matchmaker_claim:{new_conv.hubspot_ticket_id}"
        if not cache.add(claim_key, "1", timeout=60):
            logger.debug("matchmaker_ticket_already_claimed", ticket_id=new_conv.hubspot_ticket_id)
            return AssignmentOutcome.LOCKED

    try:
        return _do_assign(new_conv)
    finally:
        cache.delete(claim_key)


def _do_assign(new_conv: NewConversation) -> AssignmentOutcome:
    """Internal: perform the actual assignment after claiming a ticket."""
    # Select next agent via the 4-rule algorithm
    last_owner_id = get_last_assigned_owner_id()
    agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner_id)

    if agent is None:
        # No agent available — mark as queued
        new_conv.queue_status = NewConversation.QueueStatus.QUEUED
        new_conv.assignment_attempts += 1
        new_conv.last_assignment_attempt_at = timezone.now()
        new_conv.save(update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"])
        logger.info(
            "matchmaker_no_agent_available",
            ticket_id=new_conv.hubspot_ticket_id,
            queue_position=new_conv.queue_position,
        )
        return AssignmentOutcome.NO_AGENT

    # Reconcile agent's load with HubSpot before committing
    reconciled_count = sat_reconcile_agent_load(agent)
    max_chats = agent.max_simultaneous_chats or 5

    if reconciled_count >= max_chats:
        # Agent is at capacity after reconciliation — try next.
        # Pass the ORIGINAL last_owner_id (not the rejected agent) so Rule 2
        # correctly avoids back-to-back assignment to the previously assigned
        # agent, rather than accidentally excluding a still-eligible agent.
        logger.info(
            "matchmaker_agent_at_capacity_after_reconcile",
            agent=agent.name,
            reconciled_count=reconciled_count,
            max_chats=max_chats,
        )
        # Re-select excluding the capacity-rejected agent via Rule 2.
        # We pass the REJECTED agent's owner_id so it is skipped in the
        # next selection, not the original last_owner_id (which would
        # incorrectly block a still-eligible agent from the previous ticket).
        agent_retry = select_next_agent(last_assigned_hubspot_owner_id=agent.hubspot_owner_id)
        if agent_retry is None:
            new_conv.queue_status = NewConversation.QueueStatus.QUEUED
            new_conv.assignment_attempts += 1
            new_conv.last_assignment_attempt_at = timezone.now()
            new_conv.save(
                update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"]
            )
            return AssignmentOutcome.NO_AGENT

        # Also reconcile the retry agent's real-time load from HubSpot before
        # assigning to it — the queue_service filter uses local DB counts which
        # may lag behind actual HubSpot state.
        retry_reconciled = sat_reconcile_agent_load(agent_retry)
        retry_max = agent_retry.max_simultaneous_chats or 5
        if retry_reconciled >= retry_max:
            logger.info(
                "matchmaker_retry_agent_also_at_capacity",
                agent=agent_retry.name,
                reconciled_count=retry_reconciled,
                max_chats=retry_max,
            )
            new_conv.queue_status = NewConversation.QueueStatus.QUEUED
            new_conv.assignment_attempts += 1
            new_conv.last_assignment_attempt_at = timezone.now()
            new_conv.save(
                update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"]
            )
            return AssignmentOutcome.NO_AGENT

        agent = agent_retry

    # Assign via HubSpot API
    try:
        client = get_hubspot_client()
        client.assign_ticket_owner(new_conv.hubspot_ticket_id, agent.hubspot_owner_id)
    except HubSpotResourceNotFoundError:
        _quarantine_stale_ticket(new_conv)
        return AssignmentOutcome.STALE_TICKET
    except HubSpotAPIError as exc:
        _defer_external_failure(new_conv, exc)
        logger.error(
            "matchmaker_hubspot_assign_failed",
            ticket_id=new_conv.hubspot_ticket_id,
            agent=agent.name,
            external_status=exc.external_status,
            retryable=exc.retryable,
        )
        if exc.retryable:
            return AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR
        return AssignmentOutcome.NON_RETRYABLE_EXTERNAL_ERROR
    except ExternalServiceError:
        _defer_external_failure(new_conv, None)
        logger.error(
            "matchmaker_hubspot_assign_failed",
            ticket_id=new_conv.hubspot_ticket_id,
            agent=agent.name,
            retryable=True,
        )
        return AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR

    # Persist changes atomically
    now = timezone.now()
    wait_seconds: Decimal | None = None
    if new_conv.entered_queue_at:
        delta = now - new_conv.entered_queue_at
        wait_seconds = Decimal(str(round(delta.total_seconds(), 2)))

    with transaction.atomic():
        # Remove from pending queue
        new_conv.delete()

        # Create assigned conversation record
        AssignedConversation.objects.update_or_create(
            hubspot_ticket_id=new_conv.hubspot_ticket_id,
            defaults={
                "agent": agent,
                "hubspot_owner_id": agent.hubspot_owner_id,
                "agent_name": agent.name,
                "pipeline_id": new_conv.pipeline_id,
                "entered_queue_at": new_conv.entered_queue_at,
                "assigned_at": now,
                "queue_wait_seconds": wait_seconds,
                "contact_name": new_conv.contact_name,
                "contact_email": new_conv.contact_email,
                "priority": new_conv.priority,
                "subject": new_conv.subject,
            },
        )

        # Write assignment log
        AssignmentLog.objects.create(
            ticket_id=new_conv.hubspot_ticket_id,
            agent=agent,
            agent_name=agent.name,
            hubspot_owner_id=agent.hubspot_owner_id,
            assignment_type="automatic",
            pipeline_id=new_conv.pipeline_id,
            entered_queue_at=new_conv.entered_queue_at,
            queue_wait_seconds=wait_seconds,
        )

        # Increment agent counters
        increment_agent_chat_count(agent)
        Agent.objects.filter(pk=agent.pk).update(
            total_assignments=F("total_assignments") + 1,
        )

    logger.info(
        "matchmaker_assigned",
        ticket_id=new_conv.hubspot_ticket_id,
        agent=agent.name,
        hubspot_owner_id=agent.hubspot_owner_id,
        queue_wait_seconds=float(wait_seconds) if wait_seconds else None,
        agent_current_chats=agent.current_simultaneous_chats,
        agent_max_chats=agent.max_simultaneous_chats,
    )
    _transition_assigned_lifecycle(new_conv.hubspot_ticket_id, agent)
    return AssignmentOutcome.ASSIGNED


def _quarantine_stale_ticket(new_conv: NewConversation) -> None:
    """Remove a permanently missing HubSpot ticket from the active queue."""
    now = timezone.now()
    new_conv.queue_status = NewConversation.QueueStatus.FAILED
    new_conv.assignment_attempts += 1
    new_conv.last_assignment_attempt_at = now
    new_conv.next_assignment_attempt_at = None
    new_conv.failure_code = "hubspot_ticket_not_found"
    new_conv.failure_message = "Ticket is absent from the active HubSpot portal."
    new_conv.save(
        update_fields=[
            "queue_status",
            "assignment_attempts",
            "last_assignment_attempt_at",
            "next_assignment_attempt_at",
            "failure_code",
            "failure_message",
            "updated_at",
        ]
    )
    logger.warning(
        "matchmaker_ticket_quarantined",
        ticket_id=new_conv.hubspot_ticket_id,
        failure_code=new_conv.failure_code,
        assignment_attempts=new_conv.assignment_attempts,
    )


def _defer_external_failure(new_conv: NewConversation, exc: HubSpotAPIError | None) -> None:
    """Persist bounded exponential backoff for a non-terminal HubSpot failure."""
    now = timezone.now()
    new_conv.assignment_attempts += 1
    exponent = min(max(new_conv.assignment_attempts - 1, 0), 5)
    backoff_seconds = min(60 * (2**exponent), 1800)
    new_conv.queue_status = NewConversation.QueueStatus.QUEUED
    new_conv.last_assignment_attempt_at = now
    new_conv.next_assignment_attempt_at = now + timedelta(seconds=backoff_seconds)
    external_status = exc.external_status if exc is not None else None
    new_conv.failure_code = f"hubspot_http_{external_status}" if external_status else "hubspot_transient_error"
    new_conv.failure_message = "HubSpot owner assignment failed; retry scheduled."
    new_conv.save(
        update_fields=[
            "queue_status",
            "assignment_attempts",
            "last_assignment_attempt_at",
            "next_assignment_attempt_at",
            "failure_code",
            "failure_message",
            "updated_at",
        ]
    )
    logger.warning(
        "matchmaker_ticket_deferred",
        ticket_id=new_conv.hubspot_ticket_id,
        failure_code=new_conv.failure_code,
        retry_at=new_conv.next_assignment_attempt_at.isoformat(),
        assignment_attempts=new_conv.assignment_attempts,
    )


def matchmaker_drain_queue() -> dict:
    """Process all pending conversations in FIFO order.

    Loops ``matchmaker_assign_next()`` until no more tickets can be assigned
    (either queue is empty or no eligible agents remain).

    Returns:
        Queue processing counts, including quarantined and deferred tickets.
    """
    from apps.support.queue_service import get_eligible_agents

    total_pending = _active_queue().count()

    if total_pending == 0:
        return {
            "assigned": 0,
            "remaining": 0,
            "total_pending": 0,
            "quarantined": 0,
            "deferred": 0,
        }

    # Quick check — bail if no eligible agents at all
    if not get_eligible_agents():
        logger.debug("matchmaker_drain_no_eligible_agents", total_pending=total_pending)
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
    max_iterations = total_pending + 5  # Safety cap to prevent infinite loops

    logger.info("matchmaker_drain_started", total_pending=total_pending)

    while processed < max_iterations:
        outcome = matchmaker_assign_next()
        if outcome == AssignmentOutcome.ASSIGNED:
            assigned += 1
            processed += 1
            continue
        if outcome == AssignmentOutcome.STALE_TICKET:
            quarantined += 1
            processed += 1
            continue
        if outcome == AssignmentOutcome.RETRYABLE_EXTERNAL_ERROR:
            deferred += 1
            processed += 1
            # Stop this drain to avoid amplifying a provider outage or rate limit.
            break
        if outcome == AssignmentOutcome.NON_RETRYABLE_EXTERNAL_ERROR:
            deferred += 1
            processed += 1
            break
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
) -> NewConversation | None:
    """Validate and enqueue a ticket into new_conversations.

    Extracted from ``auto_assign_service.process_new_ticket_event()`` for
    reuse by the Matchmaker task pipeline.

    Args:
        hubspot_ticket_id: HubSpot ticket ID.
        entered_at_ms: HubSpot millisecond timestamp for queue ordering.

    Returns:
        NewConversation instance if enqueued, None if ineligible.
    """
    from apps.support.auto_assign_service import _is_ticket_eligible, _parse_hubspot_timestamp

    logger.info("matchmaker_enqueue_ticket", ticket_id=hubspot_ticket_id)

    # Fetch ticket details from HubSpot
    try:
        client = get_hubspot_client()
        ticket_data = client.get_ticket_details(hubspot_ticket_id)
    except ExternalServiceError:
        logger.error("matchmaker_hubspot_fetch_failed", ticket_id=hubspot_ticket_id)
        return None

    if not _is_ticket_eligible(ticket_data):
        return None

    entered_queue_at = _parse_hubspot_timestamp(entered_at_ms) or timezone.now()

    new_conv, created = NewConversation.objects.get_or_create(
        hubspot_ticket_id=hubspot_ticket_id,
        defaults={
            "pipeline_id": ticket_data.get("pipeline", SUPPORT_PIPELINE_ID),
            "contact_name": ticket_data.get("contact_name") or "",
            "contact_email": ticket_data.get("contact_email") or "",
            "priority": ticket_data.get("priority") or "",
            "subject": ticket_data.get("subject") or "",
            "entered_queue_at": entered_queue_at,
        },
    )

    if not created:
        if new_conv.can_reactivate:
            new_conv.queue_status = NewConversation.QueueStatus.PENDING
            new_conv.assignment_attempts = 0
            new_conv.last_assignment_attempt_at = None
            new_conv.next_assignment_attempt_at = None
            new_conv.failure_code = ""
            new_conv.failure_message = ""
            new_conv.save(
                update_fields=[
                    "queue_status",
                    "assignment_attempts",
                    "last_assignment_attempt_at",
                    "next_assignment_attempt_at",
                    "failure_code",
                    "failure_message",
                    "updated_at",
                ]
            )
            logger.info("matchmaker_ticket_reactivated", ticket_id=hubspot_ticket_id)
        else:
            logger.info("matchmaker_ticket_already_queued", ticket_id=hubspot_ticket_id)

    return new_conv


def enqueue_handoff_ticket(
    hubspot_ticket_id: str,
    *,
    pipeline_id: str = "",
    priority: str = "",
    subject: str = "",
    contact_name: str = "",
    contact_email: str = "",
) -> NewConversation:
    """Enqueue an AI handoff without applying N1 entry-stage eligibility rules."""
    new_conv, _created = NewConversation.objects.update_or_create(
        hubspot_ticket_id=str(hubspot_ticket_id),
        defaults={
            "pipeline_id": pipeline_id or SUPPORT_PIPELINE_ID,
            "priority": priority,
            "subject": subject,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "entered_queue_at": timezone.now(),
            "queue_status": NewConversation.QueueStatus.PENDING,
            "assignment_attempts": 0,
            "last_assignment_attempt_at": None,
            "next_assignment_attempt_at": None,
            "failure_code": "",
            "failure_message": "",
        },
    )
    logger.info(
        "matchmaker_handoff_enqueued",
        ticket_id=hubspot_ticket_id,
        pipeline_id=new_conv.pipeline_id,
        priority=priority or None,
    )
    return new_conv
