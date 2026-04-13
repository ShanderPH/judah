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

from decimal import Decimal

import structlog
from django.db import transaction
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID, get_hubspot_client
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


def matchmaker_assign_next() -> bool:
    """Attempt to assign the oldest pending NewConversation to the best agent.

    Uses ``select_for_update(skip_locked=True)`` to safely handle concurrent
    workers.  Before assignment, reconciles the candidate agent's load with
    HubSpot via the SAT service.

    Returns:
        True if a ticket was assigned, False if no ticket or no agent available.
    """
    # Lock the oldest pending conversation (skip if another worker has it)
    with transaction.atomic():
        new_conv = NewConversation.objects.select_for_update(skip_locked=True).order_by("entered_queue_at").first()

        if new_conv is None:
            return False

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
        return False

    # Reconcile agent's load with HubSpot before committing
    reconciled_count = sat_reconcile_agent_load(agent)
    max_chats = agent.max_simultaneous_chats or 5

    if reconciled_count >= max_chats:
        # Agent is at capacity after reconciliation — try next
        logger.info(
            "matchmaker_agent_at_capacity_after_reconcile",
            agent=agent.name,
            reconciled_count=reconciled_count,
            max_chats=max_chats,
        )
        # Re-select excluding this agent
        agent.refresh_from_db()
        agent_retry = select_next_agent(last_assigned_hubspot_owner_id=agent.hubspot_owner_id)
        if agent_retry is None:
            new_conv.queue_status = NewConversation.QueueStatus.QUEUED
            new_conv.assignment_attempts += 1
            new_conv.last_assignment_attempt_at = timezone.now()
            new_conv.save(
                update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"]
            )
            return False
        agent = agent_retry

    # Assign via HubSpot API
    try:
        client = get_hubspot_client()
        client.assign_ticket_owner(new_conv.hubspot_ticket_id, agent.hubspot_owner_id)
    except ExternalServiceError:
        logger.error(
            "matchmaker_hubspot_assign_failed",
            ticket_id=new_conv.hubspot_ticket_id,
            agent=agent.name,
        )
        return False

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
            total_assignments=agent.total_assignments + 1,
        )

    logger.info(
        "matchmaker_assigned",
        ticket_id=new_conv.hubspot_ticket_id,
        agent=agent.name,
        hubspot_owner_id=agent.hubspot_owner_id,
        queue_wait_seconds=float(wait_seconds) if wait_seconds else None,
    )
    return True


def matchmaker_drain_queue() -> dict:
    """Process all pending conversations in FIFO order.

    Loops ``matchmaker_assign_next()`` until no more tickets can be assigned
    (either queue is empty or no eligible agents remain).

    Returns:
        Dict with ``assigned``, ``remaining``, ``total_pending`` counts.
    """
    from apps.support.queue_service import get_eligible_agents

    total_pending = NewConversation.objects.count()

    if total_pending == 0:
        return {"assigned": 0, "remaining": 0, "total_pending": 0}

    # Quick check — bail if no eligible agents at all
    if not get_eligible_agents():
        logger.debug("matchmaker_drain_no_eligible_agents", total_pending=total_pending)
        return {"assigned": 0, "remaining": total_pending, "total_pending": total_pending}

    assigned = 0

    while True:
        # Re-check eligibility before each attempt
        if not get_eligible_agents():
            break

        success = matchmaker_assign_next()
        if not success:
            break

        assigned += 1

    remaining = NewConversation.objects.count()

    logger.info(
        "matchmaker_drain_done",
        total_pending=total_pending,
        assigned=assigned,
        remaining=remaining,
    )
    return {"assigned": assigned, "remaining": remaining, "total_pending": total_pending}


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
        logger.info("matchmaker_ticket_already_queued", ticket_id=hubspot_ticket_id)

    return new_conv
