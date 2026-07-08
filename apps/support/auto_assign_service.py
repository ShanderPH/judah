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


def _transition_lifecycle_best_effort(hubspot_ticket_id: str, states: list[str], *, reason: str) -> None:
    """Advance AI/helpdesk lifecycle when a support event affects a ticket."""
    try:
        from apps.ai_agents.services.lifecycle import InvalidStateTransitionError, LifecycleEngine

        engine = LifecycleEngine()
        for state in states:
            try:
                if not engine.transition_by_ticket(hubspot_ticket_id, state, reason=reason):
                    return
            except InvalidStateTransitionError as exc:
                logger.info(
                    "support_lifecycle_transition_skipped",
                    ticket_id=hubspot_ticket_id,
                    target_state=state,
                    reason=str(exc),
                )
                return
    except Exception as exc:
        logger.warning("support_lifecycle_transition_failed", ticket_id=hubspot_ticket_id, error=str(exc))


def _safe_parse_owner_id(value: str | int | None) -> int | None:
    """Safely extract a numeric HubSpot owner ID from various formats.

    HubSpot webhooks may send owner IDs in different formats:
      - ``"72733895"`` (plain numeric string)
      - ``"userId:72733895"`` (prefixed format)
      - ``"StageCalculatedPropertiesRollup"`` (non-ID property name)
      - ``None`` or empty string

    Returns:
        The integer owner ID, or None if the value is not a valid owner ID.
    """
    if not value:
        return None

    raw = str(value).strip()
    if not raw or raw in ("None", "null"):
        return None

    # Handle "userId:12345" format
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]

    try:
        return int(raw)
    except (ValueError, TypeError):  # fmt: skip  # keep parenthesized form for py<3.14 compat
        return None


def _parse_hubspot_timestamp(value: str | int | None) -> datetime | None:
    """Parse a HubSpot millisecond-epoch timestamp into a UTC datetime."""
    if not value:
        return None
    try:
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (ValueError, TypeError, OSError):  # fmt: skip  # keep parenthesized form for py<3.14 compat
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
    _transition_lifecycle_best_effort(
        hubspot_ticket_id,
        ["QUEUE_PENDING"],
        reason="Ticket enqueued for automatic assignment.",
    )

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
    # Agent status is kept fresh by the SAT heartbeat (20-second polling).
    # Load reconciliation is done per-agent by the Matchmaker before assignment.
    # No batch sync needed here.

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

    _transition_lifecycle_best_effort(
        new_conv.hubspot_ticket_id,
        ["HUMAN_ASSIGNED"],
        reason="Matchmaker assigned the ticket to a human agent.",
    )

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

    This function is fully idempotent: concurrent or duplicate calls for the
    same ticket are safe. A Redis dedup lock + ``select_for_update()`` on the
    ``AssignedConversation`` row ensures only one execution performs the
    decrement and moves the record to ``closed_conversations``.

    The agent whose count is decremented is always ``assigned.agent`` — the
    agent the ticket was auto-assigned to — regardless of who closed it.

    Args:
        hubspot_ticket_id: The HubSpot ticket ID.
        closed_at_ms: Value of ``hs_v2_date_entered_939275052`` (ms epoch).
        owner_id: The ``hubspot_owner_id`` at the time of closure (used only
            for ``closed_by_*`` metadata fields, not for count management).
    """
    from django.core.cache import cache

    # Redis dedup lock — prevent concurrent/duplicate calls (e.g., when both
    # hs_v2_date_entered_939275052 and hs_pipeline_stage webhooks fire for the
    # same closure event).
    lock_key = f"ticket_close:{hubspot_ticket_id}"
    if not cache.add(lock_key, "1", timeout=60):
        logger.info("handle_ticket_closed_dedup_skip", ticket_id=hubspot_ticket_id)
        return

    try:
        _do_handle_ticket_closed(hubspot_ticket_id, closed_at_ms, owner_id)
    finally:
        cache.delete(lock_key)


def _do_handle_ticket_closed(
    hubspot_ticket_id: str,
    closed_at_ms: str | int | None = None,
    owner_id: str | None = None,
) -> None:
    """Internal implementation of ticket closure — called only after dedup lock is held."""
    closed_at = _parse_hubspot_timestamp(closed_at_ms) or timezone.now()

    # If the ticket is still pending (never assigned), remove it from the queue
    # so it is not assigned after closure.
    pending_conv = NewConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id).first()
    if pending_conv:
        pending_conv.delete()
        logger.info("auto_assign_pending_deleted_on_close", ticket_id=hubspot_ticket_id)

    # Resolve closing agent metadata (only used for audit fields, not count management)
    closing_owner = _safe_parse_owner_id(owner_id)
    closing_agent_name: str | None = None

    if closing_owner:
        closing_agent_obj = Agent.objects.filter(hubspot_owner_id=closing_owner).first()
        if closing_agent_obj:
            closing_agent_name = closing_agent_obj.name

    # Use select_for_update to serialize concurrent closures for the same ticket.
    # If the row is already gone (another process handled it), get() raises
    # DoesNotExist which falls through to the minimal ClosedConversation path.
    try:
        with transaction.atomic():
            assigned = AssignedConversation.objects.select_for_update().get(hubspot_ticket_id=hubspot_ticket_id)

            handle_time: Decimal | None = None
            if assigned.assigned_at:
                delta = closed_at - assigned.assigned_at
                handle_time = Decimal(str(round(delta.total_seconds() / 60, 2)))

            resolution_time: Decimal | None = None
            if assigned.entered_queue_at:
                total_delta = closed_at - assigned.entered_queue_at
                resolution_time = Decimal(str(round(total_delta.total_seconds() / 60, 2)))

            # Determine closure source
            closure_source = "agent"
            if closing_owner and assigned.agent and closing_owner != assigned.hubspot_owner_id:
                closure_source = "system"  # Closed by someone other than assigned agent

            if not closing_agent_name and assigned.agent:
                closing_agent_name = assigned.agent.name

            # Decrement the ASSIGNED agent's count — always use assigned.agent,
            # regardless of who closed the ticket. This matches the increment that
            # was applied when the ticket was auto-assigned.
            if assigned.agent:
                decrement_agent_chat_count(assigned.agent)

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
                    "resolution_time_minutes": resolution_time,
                    "closure_source": closure_source,
                    "contact_name": assigned.contact_name,
                    "contact_email": assigned.contact_email,
                    "priority": assigned.priority,
                    "subject": assigned.subject,
                },
            )
            assigned.delete()

    except AssignedConversation.DoesNotExist:
        # Ticket was closed without ever being assigned (or already processed) —
        # create a minimal closed record so the event is not silently dropped.
        logger.info("auto_assign_close_no_assigned_record", ticket_id=hubspot_ticket_id)
        ClosedConversation.objects.get_or_create(
            hubspot_ticket_id=hubspot_ticket_id,
            defaults={
                "closed_at": closed_at,
                "closed_by_owner_id": closing_owner,
                "closed_by_agent_name": closing_agent_name,
            },
        )
        _transition_lifecycle_best_effort(
            hubspot_ticket_id,
            ["RESOLVED_BY_HUMAN", "CLOSED"],
            reason="HubSpot ticket closed without assigned conversation record.",
        )
        return

    _transition_lifecycle_best_effort(
        hubspot_ticket_id,
        ["RESOLVED_BY_HUMAN", "CLOSED"],
        reason="HubSpot ticket closed by support lifecycle.",
    )

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

    Also checks for tickets already tracked in ``assigned_conversations`` to
    avoid duplicates across the lifecycle tables.

    After populating the queue, immediately attempts assignment to any agent
    that is already online.

    Returns:
        Dict with ``created``, ``skipped``, ``already_assigned``,
        ``total_from_hubspot`` counts.
    """
    logger.info("sync_novo_stage_tickets_start")

    try:
        client = get_hubspot_client()
        tickets = client.search_tickets_in_novo_stage()
    except ExternalServiceError as exc:
        logger.error("sync_novo_stage_tickets_hubspot_fetch_failed", error=str(exc))
        return {"created": 0, "skipped": 0, "already_assigned": 0, "total_from_hubspot": 0, "error": str(exc)}

    created = 0
    skipped = 0
    already_assigned = 0

    # Pre-fetch existing ticket IDs to avoid N+1 queries in the loop
    ticket_ids_from_hubspot = {str(t["id"]) for t in tickets}
    existing_pending = set(
        NewConversation.objects.filter(hubspot_ticket_id__in=ticket_ids_from_hubspot).values_list(
            "hubspot_ticket_id", flat=True
        )
    )
    existing_assigned = set(
        AssignedConversation.objects.filter(hubspot_ticket_id__in=ticket_ids_from_hubspot).values_list(
            "hubspot_ticket_id", flat=True
        )
    )

    for ticket in tickets:
        ticket_id = str(ticket["id"])

        # Skip tickets that already have an owner in HubSpot — they are not
        # "new and unassigned" regardless of their pipeline stage.
        owner_id = ticket.get("owner_id", "")
        if owner_id and str(owner_id).strip() not in ("", "None", "null"):
            skipped += 1
            continue

        # Skip tickets already in our queue (pending)
        if ticket_id in existing_pending:
            skipped += 1
            continue

        # Skip tickets already assigned
        if ticket_id in existing_assigned:
            already_assigned += 1
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
        logger.info(
            "sync_novo_ticket_instanced",
            ticket_id=ticket_id,
            subject=(ticket.get("subject") or "")[:80],
            contact=ticket.get("contact_name") or "",
        )

    logger.info(
        "sync_novo_stage_tickets_done",
        total_from_hubspot=len(tickets),
        created=created,
        skipped=skipped,
        already_assigned=already_assigned,
    )

    # After populating the queue, immediately try to assign tickets to any
    # agent that is already online — so a sync that runs while agents are
    # available does not require a separate trigger.
    if created > 0:
        assign_result = assign_pending_tickets()
        logger.info(
            "sync_novo_auto_assign_triggered",
            assigned=assign_result["assigned"],
            remaining=assign_result["skipped"],
        )

    return {
        "created": created,
        "skipped": skipped,
        "already_assigned": already_assigned,
        "total_from_hubspot": len(tickets),
    }


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
