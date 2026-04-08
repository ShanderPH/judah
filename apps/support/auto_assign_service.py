"""Auto-assignment service — orchestrates ticket validation and assignment.

Flow:
  1. Webhook fires when ``hs_v2_date_entered_939275049`` changes (ticket → NOVO stage).
  2. ``process_new_ticket_event`` validates the ticket and enqueues it in
     ``new_conversations``.
  3. ``attempt_auto_assign`` selects the next eligible agent via ``queue_service``
     and updates HubSpot + local DB atomically.
  4. When a ticket is closed (``hs_v2_date_entered_939275052``),
     ``handle_ticket_closed`` calculates handle time and updates metrics.

Validation rules before assignment:
  - Ticket must belong to pipeline ``636459134``.
  - Ticket must have no current owner (``hubspot_owner_id`` is null/empty).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID, get_hubspot_client
from apps.support.models import (
    Agent,
    AgentStatusHistory,
    AssignedConversation,
    AssignmentLog,
    ClosedConversation,
    NewConversation,
)
from apps.support.queue_service import (
    decrement_agent_chat_count,
    get_last_assigned_owner_id,
    increment_agent_chat_count,
    select_next_agent,
)
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)


def _parse_hubspot_timestamp(value: str | int | None) -> datetime | None:
    """Parse a HubSpot millisecond-epoch timestamp into a UTC datetime."""
    if not value:
        return None
    try:
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except ValueError, TypeError, OSError:
        return None


def process_new_ticket_event(hubspot_ticket_id: str, entered_at_ms: str | int | None = None) -> bool:
    """Handle a ticket entering the NOVO stage.

    Validates the ticket, enqueues it in ``new_conversations``, and
    immediately attempts automatic assignment.

    Args:
        hubspot_ticket_id: The HubSpot ticket ID (string).
        entered_at_ms: The value of ``hs_v2_date_entered_939275049``
            (millisecond timestamp from HubSpot). Used as the
            ``entered_queue_at`` timestamp for wait-time metering.

    Returns:
        True if the ticket was successfully assigned, False otherwise.
    """
    logger.info("auto_assign_new_ticket_event", ticket_id=hubspot_ticket_id)

    # Fetch ticket details from HubSpot
    try:
        client = get_hubspot_client()
        ticket_data = client.get_ticket_details(hubspot_ticket_id)
    except ExternalServiceError:
        logger.error("auto_assign_hubspot_fetch_failed", ticket_id=hubspot_ticket_id)
        return False

    # Validate ticket is eligible for assignment
    if not _is_ticket_eligible(ticket_data):
        return False

    entered_queue_at = _parse_hubspot_timestamp(entered_at_ms) or timezone.now()

    # Enqueue in new_conversations (idempotent)
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
        logger.info("auto_assign_ticket_already_queued", ticket_id=hubspot_ticket_id)

    return attempt_auto_assign(new_conv, ticket_data)


def _is_ticket_eligible(ticket_data: dict) -> bool:
    """Validate that a ticket meets all prerequisites for auto-assignment.

    Rules:
      1. Must belong to pipeline ``636459134``.
      2. Must have no current owner.

    Args:
        ticket_data: Dict from ``HubSpotClient.get_ticket_details``.

    Returns:
        True if eligible, False otherwise.
    """
    ticket_id = ticket_data.get("id", "?")
    pipeline = ticket_data.get("pipeline", "")
    owner_id = ticket_data.get("owner_id", "")

    if str(pipeline) != SUPPORT_PIPELINE_ID:
        logger.info(
            "auto_assign_ticket_wrong_pipeline",
            ticket_id=ticket_id,
            pipeline=pipeline,
        )
        return False

    if owner_id and str(owner_id).strip() not in ("", "None", "null"):
        logger.info(
            "auto_assign_ticket_already_has_owner",
            ticket_id=ticket_id,
            owner_id=owner_id,
        )
        return False

    return True


def attempt_auto_assign(new_conv: NewConversation, ticket_data: dict | None = None) -> bool:
    """Try to assign a pending NewConversation to the next eligible agent.

    This is idempotent — if the conversation is already assigned it returns False.

    When no agent is available, the conversation's ``queue_status`` is updated
    to ``"queued"`` so it remains in the queue for assignment when an agent
    becomes available.

    Before assignment, performs a parallel sync of all helpdesk agents' status
    and conversation counts from HubSpot to ensure accurate availability data.

    Args:
        new_conv: The NewConversation instance to assign.
        ticket_data: Optional pre-fetched ticket data dict. If None, will be
            fetched from HubSpot.

    Returns:
        True if assignment succeeded, False otherwise.
    """
    # Sync all agents' status and conversation counts before assignment
    # This ensures we have the most up-to-date availability data
    try:
        sync_all_agents_status_and_counts()
    except Exception as sync_exc:
        logger.warning(
            "auto_assign_pre_sync_failed",
            ticket_id=new_conv.hubspot_ticket_id,
            error=str(sync_exc),
        )
        # Continue with assignment even if sync fails — use cached data

    # Select next agent (Rule 1-4)
    last_owner_id = get_last_assigned_owner_id()
    agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner_id)

    if agent is None:
        # No agent available — mark as queued for later assignment
        new_conv.queue_status = NewConversation.QueueStatus.QUEUED
        new_conv.assignment_attempts += 1
        new_conv.last_assignment_attempt_at = timezone.now()
        new_conv.save(update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"])
        logger.warning(
            "auto_assign_no_agent_available",
            ticket_id=new_conv.hubspot_ticket_id,
            queue_position=new_conv.queue_position,
            assignment_attempts=new_conv.assignment_attempts,
        )
        return False

    # Verify selected agent is still available (double-check after sync)
    agent.refresh_from_db()
    if agent.status_enum != Agent.StatusEnum.ONLINE:
        logger.warning(
            "auto_assign_agent_no_longer_available",
            ticket_id=new_conv.hubspot_ticket_id,
            agent=agent.name,
            status=agent.status_enum,
        )
        # Re-select agent with updated data
        agent = select_next_agent(last_assigned_hubspot_owner_id=last_owner_id)
        if agent is None:
            new_conv.queue_status = NewConversation.QueueStatus.QUEUED
            new_conv.assignment_attempts += 1
            new_conv.last_assignment_attempt_at = timezone.now()
            new_conv.save(
                update_fields=["queue_status", "assignment_attempts", "last_assignment_attempt_at", "updated_at"]
            )
            return False

    # Assign via HubSpot API
    try:
        client = get_hubspot_client()
        client.assign_ticket_owner(new_conv.hubspot_ticket_id, agent.hubspot_owner_id)
    except ExternalServiceError:
        logger.error(
            "auto_assign_hubspot_update_failed",
            ticket_id=new_conv.hubspot_ticket_id,
            agent_id=str(agent.id),
        )
        return False

    # Persist changes atomically in local DB
    now = timezone.now()
    wait_seconds: Decimal | None = None
    if new_conv.entered_queue_at:
        delta = now - new_conv.entered_queue_at
        wait_seconds = Decimal(str(round(delta.total_seconds(), 2)))

    with transaction.atomic():
        # Remove from pending queue — the record moves to assigned_conversations
        new_conv.delete()

        # Create or update assigned_conversation record
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

        # Write to assignment_logs
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

        # Update agent chat counter
        increment_agent_chat_count(agent)

    logger.info(
        "auto_assign_success",
        ticket_id=new_conv.hubspot_ticket_id,
        agent_name=agent.name,
        hubspot_owner_id=agent.hubspot_owner_id,
        queue_wait_seconds=float(wait_seconds) if wait_seconds is not None else None,
    )
    return True


def handle_ticket_closed(
    hubspot_ticket_id: str,
    closed_at_ms: str | int | None = None,
    owner_id: str | None = None,
) -> None:
    """Handle a ticket entering the FECHADO (closed) stage.

    Updates the ``assigned_conversations`` record with closure metadata,
    calculates total handle time, and decrements the agent's chat counter.

    Args:
        hubspot_ticket_id: The HubSpot ticket ID.
        closed_at_ms: Value of ``hs_v2_date_entered_939275052`` (ms epoch).
        owner_id: The ``hubspot_owner_id`` at the time of closure (the
            agent who closed the ticket).
    """
    closed_at = _parse_hubspot_timestamp(closed_at_ms) or timezone.now()

    # If the ticket is still pending (never assigned), remove it from the queue
    # so it is not assigned after closure.
    pending_conv = NewConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id).first()
    if pending_conv:
        pending_conv.delete()
        logger.info("auto_assign_pending_deleted_on_close", ticket_id=hubspot_ticket_id)

    # Resolve closing agent info
    closing_owner = int(owner_id) if owner_id and str(owner_id).strip() else None
    closing_agent_name: str | None = None
    closing_agent_obj: Agent | None = None

    if closing_owner:
        closing_agent_obj = Agent.objects.filter(hubspot_owner_id=closing_owner).first()
        if closing_agent_obj:
            closing_agent_name = closing_agent_obj.name

    try:
        assigned = AssignedConversation.objects.get(hubspot_ticket_id=hubspot_ticket_id)
    except AssignedConversation.DoesNotExist:
        # Ticket was closed without ever being assigned — create a minimal closed record
        logger.info("auto_assign_close_no_assigned_record", ticket_id=hubspot_ticket_id)
        ClosedConversation.objects.get_or_create(
            hubspot_ticket_id=hubspot_ticket_id,
            defaults={
                "closed_at": closed_at,
                "closed_by_owner_id": closing_owner,
                "closed_by_agent_name": closing_agent_name,
            },
        )
        return

    handle_time: Decimal | None = None
    if assigned.assigned_at:
        delta = closed_at - assigned.assigned_at
        handle_time = Decimal(str(round(delta.total_seconds() / 60, 2)))

    # Decrement the assigned agent's chat count
    decrement_target = closing_agent_obj or assigned.agent
    if decrement_target:
        decrement_agent_chat_count(decrement_target)
    if not closing_agent_name and assigned.agent:
        closing_agent_name = assigned.agent.name

    with transaction.atomic():
        # Move from assigned_conversations → closed_conversations
        ClosedConversation.objects.get_or_create(
            hubspot_ticket_id=hubspot_ticket_id,
            defaults={
                "agent": assigned.agent,
                "hubspot_owner_id": assigned.hubspot_owner_id,
                "agent_name": assigned.agent_name,
                "pipeline_id": assigned.pipeline_id,
                "entered_queue_at": assigned.entered_queue_at,
                "assigned_at": assigned.assigned_at,
                "closed_at": closed_at,
                "closed_by_owner_id": closing_owner,
                "closed_by_agent_name": closing_agent_name,
                "queue_wait_seconds": assigned.queue_wait_seconds,
                "total_handle_time_minutes": handle_time,
                "contact_name": assigned.contact_name,
                "contact_email": assigned.contact_email,
                "priority": assigned.priority,
                "subject": assigned.subject,
            },
        )
        assigned.delete()

    logger.info(
        "auto_assign_ticket_closed",
        ticket_id=hubspot_ticket_id,
        closed_by_owner_id=closing_owner,
        handle_time_minutes=float(handle_time) if handle_time is not None else None,
    )


def assign_pending_tickets() -> dict:
    """Try to assign all tickets currently pending in new_conversations.

    Called when an agent comes online (via webhook or polling) so that tickets
    that arrived while no agent was available are promptly picked up — not just
    tickets that trigger a new webhook event.

    Iterates oldest-first so the queue is FIFO.  Stops as soon as there are no
    more eligible agents to avoid unnecessary HubSpot API calls.

    Returns:
        Dict with ``assigned``, ``skipped``, ``total_pending`` counts.
    """
    from apps.support.queue_service import get_eligible_agents

    pending = list(NewConversation.objects.all().order_by("entered_queue_at"))
    total = len(pending)

    if not total:
        return {"assigned": 0, "skipped": 0, "total_pending": 0}

    # Quick check before iterating — bail early if no eligible agents
    if not get_eligible_agents():
        logger.debug("assign_pending_tickets_no_eligible_agents", total_pending=total)
        return {"assigned": 0, "skipped": total, "total_pending": total}

    assigned = 0
    skipped = 0

    for conv in pending:
        # Re-check eligibility before each assignment (agent may fill up mid-loop)
        if not get_eligible_agents():
            skipped += total - assigned - skipped
            break

        try:
            success = attempt_auto_assign(conv)
        except Exception as exc:
            logger.warning(
                "assign_pending_tickets_error",
                ticket_id=conv.hubspot_ticket_id,
                error=str(exc),
            )
            skipped += 1
            continue

        if success:
            assigned += 1
        else:
            skipped += 1

    logger.info(
        "assign_pending_tickets_done",
        total_pending=total,
        assigned=assigned,
        skipped=skipped,
    )
    return {"assigned": assigned, "skipped": skipped, "total_pending": total}


def sync_novo_stage_tickets() -> dict:
    """Sync tickets currently in the NOVO stage from HubSpot into new_conversations.

    Fetches every ticket in pipeline ``636459134`` / stage ``939275049`` and
    creates a ``NewConversation`` record for those not yet present in the local
    queue.  Records that already exist (assigned or pending) are skipped so
    this operation is fully idempotent.

    This is intentionally NOT assigning — it only populates the queue so that
    tickets are ready to be picked up as soon as an agent comes online.

    Returns:
        Dict with ``created``, ``skipped``, ``total_from_hubspot`` counts.
    """
    logger.info("sync_novo_stage_tickets_start")

    try:
        client = get_hubspot_client()
        tickets = client.search_tickets_in_novo_stage()
    except ExternalServiceError as exc:
        logger.error("sync_novo_stage_tickets_hubspot_fetch_failed", error=str(exc))
        return {"created": 0, "skipped": 0, "total_from_hubspot": 0, "error": str(exc)}

    created = 0
    skipped = 0

    for ticket in tickets:
        ticket_id = str(ticket["id"])

        # Skip tickets that already have an owner in HubSpot — they are not
        # "new and unassigned" regardless of their pipeline stage.
        owner_id = ticket.get("owner_id", "")
        if owner_id and str(owner_id).strip() not in ("", "None", "null"):
            logger.debug("sync_novo_ticket_has_owner_skipped", ticket_id=ticket_id, owner_id=owner_id)
            skipped += 1
            continue

        # Skip tickets already in our queue (pending or already assigned)
        if NewConversation.objects.filter(hubspot_ticket_id=ticket_id).exists():
            skipped += 1
            continue

        entered_at = _parse_hubspot_timestamp(ticket.get("entered_novo_at")) or timezone.now()

        NewConversation.objects.create(
            hubspot_ticket_id=ticket_id,
            pipeline_id=ticket.get("pipeline") or SUPPORT_PIPELINE_ID,
            contact_name=ticket.get("contact_name") or "",
            contact_email=ticket.get("contact_email") or "",
            priority=ticket.get("priority") or "",
            subject=ticket.get("subject") or "",
            entered_queue_at=entered_at,
        )
        created += 1
        logger.info("sync_novo_ticket_queued", ticket_id=ticket_id)

    logger.info(
        "sync_novo_stage_tickets_done",
        total_from_hubspot=len(tickets),
        created=created,
        skipped=skipped,
    )

    # After populating the queue, immediately try to assign tickets to any
    # agent that is already online — so a sync that runs while agents are
    # available does not require a separate trigger.
    if created > 0:
        assign_pending_tickets()

    return {"created": created, "skipped": skipped, "total_from_hubspot": len(tickets)}


def sync_hubspot_team_to_agents(team_id: str) -> int:
    """Sync HubSpot team members into the local agents table.

    For each team member not yet in the agents table, creates an Agent record.
    Existing agents are not modified (preserves manual configurations).

    Args:
        team_id: The HubSpot team ID to sync.

    Returns:
        Number of new agents created.
    """
    try:
        client = get_hubspot_client()
        members = client.get_team_members(team_id)
    except ExternalServiceError:
        logger.error("auto_assign_team_sync_failed", team_id=team_id)
        return 0

    created_count = 0
    for member in members:
        owner_id = member.get("id")
        email = member.get("email", "")
        first = member.get("first_name", "")
        last = member.get("last_name", "")
        name = f"{first} {last}".strip() or email

        if not owner_id or not email:
            continue

        _, created = Agent.objects.get_or_create(
            hubspot_owner_id=int(owner_id),
            defaults={
                "name": name,
                "agent_email": email,
                "status_enum": Agent.StatusEnum.OFFLINE,
                "current_simultaneous_chats": 0,
                "max_simultaneous_chats": 5,
                "auto_assign_enabled": True,
                "is_active": True,
                "team": f"team_{team_id}",
            },
        )
        if created:
            created_count += 1
            logger.info("auto_assign_agent_synced", email=email, hubspot_owner_id=owner_id)

    logger.info("auto_assign_team_sync_complete", team_id=team_id, created=created_count)
    return created_count


def sync_all_agents_status_and_counts() -> dict:
    """Sync all helpdesk agents' status and conversation counts from HubSpot.

    This function performs a parallel sync of:
    1. Agent availability status (online/away) from HubSpot Users API
    2. Active conversation count per agent from HubSpot Tickets Search API

    The sync is optimized to run before each assignment to ensure accurate
    availability data, minimizing the risk of assigning to unavailable agents.

    Returns:
        Dict with ``agents_synced``, ``status_changes``, ``count_corrections`` keys.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = get_hubspot_client()

    # Get all active agents from local DB
    agents = list(Agent.objects.filter(is_active=True).exclude(hubspot_owner_id__isnull=True))
    if not agents:
        logger.debug("sync_all_agents_no_active_agents")
        return {"agents_synced": 0, "status_changes": 0, "count_corrections": 0}

    # Fetch availability status for all users in one call
    try:
        availability_data = client.get_all_owners_availability()
        availability_map = {
            item.get("email", "").lower(): item.get("status_enum", "away") for item in availability_data
        }
    except Exception as exc:
        logger.warning("sync_all_agents_availability_fetch_failed", error=str(exc))
        availability_map = {}

    # Fetch conversation counts in parallel for each agent
    count_map: dict[int, int] = {}

    def fetch_count(agent: Agent) -> tuple[int, int]:
        count = client.count_active_tickets_by_owner(agent.hubspot_owner_id)
        return (agent.hubspot_owner_id, count)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_count, agent): agent for agent in agents}
        for future in as_completed(futures):
            try:
                owner_id, count = future.result()
                if count >= 0:  # -1 indicates error
                    count_map[owner_id] = count
            except Exception as exc:
                agent = futures[future]
                logger.warning(
                    "sync_agent_count_fetch_error",
                    agent=agent.name,
                    error=str(exc),
                )

    # Apply updates to agents
    status_changes = 0
    count_corrections = 0
    now = timezone.now()

    for agent in agents:
        updates = []
        email_lower = (agent.agent_email or "").lower()

        # Update status from availability map
        if email_lower in availability_map:
            new_status = availability_map[email_lower]
            if agent.status_enum != new_status:
                old_status = agent.status_enum
                agent.status_enum = new_status
                updates.append("status_enum")
                status_changes += 1

                # Log status change
                AgentStatusHistory.objects.create(
                    agent=agent,
                    old_status=old_status,
                    new_status=new_status,
                    sync_source="pre_assignment_sync",
                )
                logger.info(
                    "sync_agent_status_updated",
                    agent=agent.name,
                    old_status=old_status,
                    new_status=new_status,
                )

        # Update conversation count from HubSpot
        if agent.hubspot_owner_id in count_map:
            hubspot_count = count_map[agent.hubspot_owner_id]
            if agent.current_simultaneous_chats != hubspot_count:
                old_count = agent.current_simultaneous_chats
                agent.current_simultaneous_chats = hubspot_count
                updates.append("current_simultaneous_chats")
                count_corrections += 1
                logger.info(
                    "sync_agent_count_corrected",
                    agent=agent.name,
                    old_count=old_count,
                    new_count=hubspot_count,
                )

        if updates:
            agent.updated_at = now
            updates.append("updated_at")
            agent.save(update_fields=updates)

    logger.info(
        "sync_all_agents_complete",
        agents_synced=len(agents),
        status_changes=status_changes,
        count_corrections=count_corrections,
    )

    return {
        "agents_synced": len(agents),
        "status_changes": status_changes,
        "count_corrections": count_corrections,
    }
