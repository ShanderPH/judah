"""Auto-assignment service — orchestrates ticket validation and assignment.

Flow:
  1. Webhook fires when the configured NOVO-stage timestamp changes.
  2. ``process_new_ticket_event`` validates the ticket and enqueues it in
     ``new_conversations``.
  3. ``attempt_auto_assign`` selects the next eligible agent via ``queue_service``
     and updates HubSpot + local DB atomically.
  4. When a ticket enters the configured closed stage,
     ``handle_ticket_closed`` calculates handle time and updates metrics.

Validation rules before assignment:
  - Ticket must belong to ``HUBSPOT_SUPPORT_PIPELINE_ID``.
  - Ticket must have no current owner (``hubspot_owner_id`` is null/empty).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID, get_hubspot_client
from apps.support.models import (
    Agent,
    AssignedConversation,
    ClosedConversation,
    NewConversation,
    SupportConversationCycle,
)
from apps.support.queue_service import decrement_agent_chat_count
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
        entered_at_ms: The configured NOVO-stage entry timestamp
            (millisecond timestamp from HubSpot). Used as the
            ``entered_queue_at`` timestamp for wait-time metering.

    Returns:
        True if the ticket was successfully assigned, False otherwise.
    """
    from apps.support.availability_runtime import (
        log_runtime_rejection,
        may_assign,
        may_ingest_queue,
    )

    if not may_ingest_queue():
        log_runtime_rejection("process_new_ticket_event")
        return False

    from apps.support.matchmaker_service import enqueue_new_ticket

    logger.info("auto_assign_new_ticket_event", ticket_id=hubspot_ticket_id)
    new_conv = enqueue_new_ticket(hubspot_ticket_id, entered_at_ms)
    if new_conv is None:
        return False
    _transition_lifecycle_best_effort(
        hubspot_ticket_id,
        ["QUEUE_PENDING"],
        reason="Ticket enqueued for automatic assignment.",
    )

    if not may_assign():
        logger.info("auto_assign_disabled_queue_preserved", ticket_id=hubspot_ticket_id)
        return False
    return attempt_auto_assign(new_conv)


def _is_ticket_eligible(ticket_data: dict) -> bool:
    """Validate that a ticket meets all prerequisites for auto-assignment.

    Rules:
      1. Must belong to ``HUBSPOT_SUPPORT_PIPELINE_ID``.
      2. Must have no current owner.

    Args:
        ticket_data: Dict from ``HubSpotClient.get_ticket_details``.

    Returns:
        True if eligible, False otherwise.
    """
    ticket_id = ticket_data.get("id", "?")
    pipeline = ticket_data.get("pipeline", "")
    owner_id = ticket_data.get("owner_id", "")
    stage = ticket_data.get("stage", "")

    if str(pipeline) != SUPPORT_PIPELINE_ID:
        logger.info(
            "auto_assign_ticket_wrong_pipeline",
            ticket_id=ticket_id,
            pipeline=pipeline,
        )
        return False

    if stage and str(stage) != settings.HUBSPOT_SUPPORT_NEW_STAGE_ID:
        logger.info(
            "auto_assign_ticket_not_in_novo",
            ticket_id=ticket_id,
            stage=stage,
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
    from apps.support.availability_runtime import log_runtime_rejection, may_assign

    if not may_assign():
        log_runtime_rejection("attempt_auto_assign")
        return False

    # Matchmaker is the sole automatic assignment implementation. Keeping this
    # compatibility entrypoint prevents legacy callers from bypassing the final
    # eligibility guard and capacity reservation.
    from apps.support.matchmaker_service import AssignmentOutcome, matchmaker_assign_next

    return matchmaker_assign_next() == AssignmentOutcome.ASSIGNED


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
        closed_at_ms: Value of the configured closed-stage timestamp (ms epoch).
        owner_id: The ``hubspot_owner_id`` at the time of closure (used only
            for ``closed_by_*`` metadata fields, not for count management).
    """
    from django.core.cache import cache

    from apps.support.availability_runtime import (
        log_runtime_rejection,
        may_write_routing_state,
    )

    if not may_write_routing_state():
        log_runtime_rejection("handle_ticket_closed")
        return

    # Redis dedup lock — prevent concurrent/duplicate calls (e.g., when both
    # Closed-stage timestamp and hs_pipeline_stage webhooks fire for the
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
    closed_at = _parse_hubspot_timestamp(closed_at_ms)
    if closed_at is None and bool(getattr(settings, "CONVERSATION_CYCLES_ENFORCED", False)):
        logger.warning("auto_assign_close_identity_unavailable", ticket_id=hubspot_ticket_id)
        return
    closed_at = closed_at or timezone.now()

    active_cycle = (
        SupportConversationCycle.objects.filter(
            hubspot_ticket_id=hubspot_ticket_id,
            state__in=["queued", "assigned", "repair_required"],
        )
        .order_by("-entered_stage_at")
        .first()
    )
    if active_cycle is not None and closed_at < active_cycle.entered_stage_at:
        logger.info("auto_assign_close_stale_cycle", ticket_id=hubspot_ticket_id, cycle_id=str(active_cycle.pk))
        return

    # If the ticket is still pending (never assigned), remove it from the queue
    # so it is not assigned after closure.
    pending_qs = NewConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id)
    if active_cycle is not None:
        pending_qs = pending_qs.filter(cycle=active_cycle)
    pending_conv = pending_qs.first()
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
            assigned_qs = AssignedConversation.objects.select_for_update().filter(hubspot_ticket_id=hubspot_ticket_id)
            if active_cycle is not None:
                assigned_qs = assigned_qs.filter(cycle=active_cycle)
            assigned = assigned_qs.get()

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
            lookup = {"cycle": active_cycle} if active_cycle is not None else {"hubspot_ticket_id": hubspot_ticket_id}
            ClosedConversation.objects.get_or_create(
                **lookup,
                defaults={
                    "hubspot_ticket_id": hubspot_ticket_id,
                    "cycle": assigned.cycle,
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
            if active_cycle is not None:
                active_cycle.state = SupportConversationCycle.State.CLOSED
                active_cycle.closed_at = closed_at
                active_cycle.save(update_fields=["state", "closed_at", "updated_at"])

    except AssignedConversation.DoesNotExist:
        # Ticket was closed without ever being assigned (or already processed) —
        # create a minimal closed record so the event is not silently dropped.
        logger.info("auto_assign_close_no_assigned_record", ticket_id=hubspot_ticket_id)
        lookup = {"cycle": active_cycle} if active_cycle is not None else {"hubspot_ticket_id": hubspot_ticket_id}
        ClosedConversation.objects.get_or_create(
            **lookup,
            defaults={
                "hubspot_ticket_id": hubspot_ticket_id,
                "cycle": pending_conv.cycle if pending_conv is not None else None,
                "closed_at": closed_at,
                "closed_by_owner_id": closing_owner,
                "closed_by_agent_name": closing_agent_name,
            },
        )
        if active_cycle is not None:
            active_cycle.state = SupportConversationCycle.State.CLOSED
            active_cycle.closed_at = closed_at
            active_cycle.save(update_fields=["state", "closed_at", "updated_at"])
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
        cycle_id=str(active_cycle.pk) if active_cycle is not None else None,
        closed_by_owner_id=closing_owner,
        handle_time_minutes=float(handle_time) if handle_time is not None else None,
    )


def assign_pending_tickets() -> dict:
    """Drain pending tickets through the canonical matchmaker.

    Called when an agent comes online (via webhook or polling) so that tickets
    that arrived while no agent was available are promptly picked up — not just
    tickets that trigger a new webhook event.

    The matchmaker owns FIFO ordering, retries, and stale-ticket quarantine.

    Returns:
        Dict with ``assigned``, ``skipped``, ``total_pending`` counts.
    """
    from apps.support.availability_runtime import may_assign
    from apps.support.matchmaker_service import matchmaker_drain_queue

    if not may_assign():
        result = matchmaker_drain_queue()
        return {
            "assigned": 0,
            "skipped": result["remaining"],
            "total_pending": result["total_pending"],
        }

    result = matchmaker_drain_queue()
    return {
        "assigned": result["assigned"],
        "skipped": result["remaining"],
        "total_pending": result["total_pending"],
    }


def sync_novo_stage_tickets() -> dict:
    """Sync tickets currently in the NOVO stage from HubSpot into new_conversations.

    Fetches every ticket in the configured support pipeline / NOVO stage and
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
    from apps.support.availability_runtime import (
        log_runtime_rejection,
        may_assign,
        may_reconcile_queue,
    )

    if not may_reconcile_queue():
        log_runtime_rejection("sync_novo_stage_tickets")
        return {"created": 0, "skipped": 0, "already_assigned": 0, "total_from_hubspot": 0}

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
    existing_pending = {
        conversation.hubspot_ticket_id: conversation
        for conversation in NewConversation.objects.filter(hubspot_ticket_id__in=ticket_ids_from_hubspot)
    }
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
            conversation = existing_pending[ticket_id]
            if conversation.can_reactivate:
                conversation.queue_status = NewConversation.QueueStatus.PENDING
                conversation.automatic_assignment_eligible = False
                conversation.assignment_attempts = 0
                conversation.last_assignment_attempt_at = None
                conversation.next_assignment_attempt_at = None
                conversation.failure_code = ""
                conversation.failure_message = ""
                conversation.save(
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
                created += 1
                logger.info("sync_novo_ticket_reactivated", ticket_id=ticket_id)
                continue
            skipped += 1
            continue

        # Skip tickets already assigned
        if ticket_id in existing_assigned:
            already_assigned += 1
            continue

        entered_at = _parse_hubspot_timestamp(ticket.get("entered_novo_at"))
        if entered_at is None:
            skipped += 1
            logger.warning("sync_novo_ticket_identity_unavailable", ticket_id=ticket_id)
            continue

        from apps.support.conversation_cycle_service import (
            CycleClassification,
            open_or_get_cycle,
        )

        cycle_result = open_or_get_cycle(
            hubspot_ticket_id=ticket_id,
            entered_stage_value=ticket.get("entered_novo_at"),
        )
        cycle = (
            cycle_result.cycle
            if cycle_result.admission.classification in (CycleClassification.CREATED, CycleClassification.DUPLICATE)
            else None
        )
        if cycle is None and settings.CONVERSATION_CYCLES_ENFORCED:
            skipped += 1
            logger.warning(
                "sync_novo_ticket_cycle_blocked",
                ticket_id=ticket_id,
                classification=cycle_result.admission.classification.value,
            )
            continue

        NewConversation.objects.create(
            hubspot_ticket_id=ticket_id,
            cycle=cycle,
            pipeline_id=ticket.get("pipeline") or SUPPORT_PIPELINE_ID,
            contact_name=ticket.get("contact_name") or "",
            contact_email=ticket.get("contact_email") or "",
            priority=ticket.get("priority") or "",
            subject=ticket.get("subject") or "",
            entered_queue_at=entered_at,
            automatic_assignment_eligible=False,
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
    if created > 0 and may_assign():
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
    from apps.support.availability_runtime import (
        is_authoritative_availability_runtime,
        log_runtime_rejection,
    )

    if not is_authoritative_availability_runtime():
        log_runtime_rejection("sync_hubspot_team_to_agents")
        return 0

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
