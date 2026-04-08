"""Handler for HubSpot webhook events."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# HubSpot property names that trigger auto-assignment logic
_PROP_STAGE_NOVO = "hs_v2_date_entered_939275049"  # Ticket entered NOVO stage
_PROP_STAGE_CLOSED = "hs_v2_date_entered_939275052"  # Ticket entered FECHADO stage
_PROP_PIPELINE_STAGE = "hs_pipeline_stage"
_PROP_OWNER_ID = "hubspot_owner_id"  # Ticket owner (agent) assignment
_PROP_AVAILABILITY = "hs_availability_status"  # User/owner availability

# Stage IDs
_STAGE_FECHADO_ID = "939275052"


def handle_hubspot_event(event) -> None:
    """Route and process a HubSpot webhook event.

    Args:
        event: WebhookEvent instance with source=hubspot.
    """
    event_type: str = event.event_type
    payload: dict = event.payload
    et_lower = event_type.lower()

    logger.info("hubspot_event_received", event_type=event_type, event_id=event.pk)

    if et_lower.startswith("ticket."):
        _handle_ticket_event(event_type, payload)
    elif et_lower.startswith("contact."):
        _handle_contact_event(event_type, payload)
    elif et_lower.startswith("conversation."):
        _handle_conversation_event(event_type, payload)
    elif et_lower.startswith(("deal.", "company.")):
        logger.debug("hubspot_crm_event_logged", event_type=event_type, object_id=payload.get("objectId"))
    else:
        logger.debug("hubspot_event_unhandled", event_type=event_type)


def _handle_ticket_event(event_type: str, payload: dict) -> None:
    """Process ticket-related HubSpot events."""
    object_id = str(payload.get("objectId", ""))
    if not object_id:
        return

    property_name = payload.get("propertyName", "")
    property_value = payload.get("propertyValue", "")

    if event_type == "ticket.propertyChange":
        if property_name == _PROP_STAGE_NOVO:
            _handle_ticket_entered_novo(object_id, property_value)

        elif property_name == _PROP_STAGE_CLOSED:
            _handle_ticket_entered_closed(object_id, property_value, payload)

        elif property_name == _PROP_PIPELINE_STAGE:
            _handle_pipeline_stage_change(object_id, property_value)

        elif property_name == _PROP_OWNER_ID:
            _handle_ticket_owner_change(object_id, property_value, payload)

    elif event_type in ("ticket.creation", "ticket.created"):
        logger.debug("hubspot_ticket_created_event", ticket_id=object_id)
    else:
        logger.debug("hubspot_ticket_event_unhandled", event_type=event_type, ticket_id=object_id)


def _handle_ticket_entered_novo(hubspot_ticket_id: str, entered_at_ms: str | None) -> None:
    """Trigger the auto-assignment flow when a ticket enters the NOVO stage.

    Executes synchronously within the webhook request to guarantee processing
    regardless of Celery worker availability.
    """
    logger.info("hubspot_ticket_entered_novo", ticket_id=hubspot_ticket_id, entered_at_ms=entered_at_ms)

    try:
        from apps.support.auto_assign_service import process_new_ticket_event

        process_new_ticket_event(hubspot_ticket_id, entered_at_ms)
    except Exception as exc:
        logger.error(
            "auto_assign_novo_handler_failed",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
        )


def _handle_ticket_entered_closed(hubspot_ticket_id: str, closed_at_ms: str | None, payload: dict) -> None:
    """Track ticket closure — moves record to closed_conversations."""
    logger.info("hubspot_ticket_entered_closed", ticket_id=hubspot_ticket_id, closed_at_ms=closed_at_ms)

    try:
        from apps.support.auto_assign_service import handle_ticket_closed

        handle_ticket_closed(hubspot_ticket_id, closed_at_ms)
    except Exception as exc:
        logger.error(
            "auto_assign_close_handler_failed",
            ticket_id=hubspot_ticket_id,
            error=str(exc),
        )


def _handle_pipeline_stage_change(object_id: str, new_stage: str) -> None:
    """Update local ticket status when HubSpot pipeline stage changes.

    When a ticket moves to FECHADO (stage 939275052), also remove it from the
    pending queue so it is never assigned after closure.
    """
    from apps.support.models import Ticket

    # If ticket moved to FECHADO, trigger the closure flow (removes from queue)
    if new_stage == _STAGE_FECHADO_ID:
        logger.info("hubspot_ticket_pipeline_stage_fechado", ticket_id=object_id)
        _handle_ticket_entered_closed(object_id, None, {})
        return

    try:
        ticket = Ticket.objects.get(ticket_id=object_id)
        ticket.status = "RESOLVED"
        ticket.save(update_fields=["status", "updated_at"])
        logger.info("ticket_resolved_via_hubspot", ticket_id=ticket.pk)
    except Ticket.DoesNotExist:
        logger.debug("hubspot_ticket_not_synced_locally", hubspot_id=object_id)


def _handle_ticket_owner_change(
    hubspot_ticket_id: str,
    new_owner_id: str | None,
    payload: dict,
) -> None:
    """Handle ticket owner (agent) reassignment.

    When a ticket's hubspot_owner_id changes, this indicates a manual reassignment
    by an agent in HubSpot. We need to:
    1. Decrement the previous owner's conversation count
    2. Increment the new owner's conversation count
    3. Update the AssignedConversation record
    4. Log the reassignment for metrics

    Args:
        hubspot_ticket_id: The HubSpot ticket ID.
        new_owner_id: The new hubspot_owner_id value (may be empty if unassigned).
        payload: Full webhook payload containing previousValue.
    """
    from decimal import Decimal

    from django.db import transaction
    from django.utils import timezone

    from apps.support.models import Agent, AssignedConversation, ConversationReassignment
    from apps.support.queue_service import decrement_agent_chat_count, increment_agent_chat_count

    previous_owner_id = payload.get("previousValue") or payload.get("sourceId")
    new_owner = new_owner_id.strip() if new_owner_id else ""
    prev_owner = str(previous_owner_id).strip() if previous_owner_id else ""

    # Skip if no actual change or if this is an initial assignment (no previous owner)
    if not prev_owner or prev_owner in ("", "None", "null"):
        logger.debug(
            "ticket_owner_change_initial_assignment",
            ticket_id=hubspot_ticket_id,
            new_owner_id=new_owner,
        )
        return

    # Skip if new owner is the same as previous (no actual change)
    if new_owner == prev_owner:
        logger.debug(
            "ticket_owner_change_same_owner",
            ticket_id=hubspot_ticket_id,
            owner_id=new_owner,
        )
        return

    logger.info(
        "ticket_owner_change_detected",
        ticket_id=hubspot_ticket_id,
        from_owner_id=prev_owner,
        to_owner_id=new_owner,
    )

    now = timezone.now()

    # Resolve agents
    from_agent: Agent | None = None
    to_agent: Agent | None = None

    try:
        prev_owner_int = int(prev_owner)
        from_agent = Agent.objects.filter(hubspot_owner_id=prev_owner_int).first()
    except (ValueError, TypeError):
        pass

    if new_owner and new_owner not in ("", "None", "null"):
        try:
            new_owner_int = int(new_owner)
            to_agent = Agent.objects.filter(hubspot_owner_id=new_owner_int).first()
        except (ValueError, TypeError):
            pass

    # Calculate time with previous agent
    time_with_prev_seconds: Decimal | None = None
    assigned_conv = AssignedConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id).first()

    if assigned_conv and assigned_conv.assigned_at:
        delta = now - assigned_conv.assigned_at
        time_with_prev_seconds = Decimal(str(round(delta.total_seconds(), 2)))

    with transaction.atomic():
        # 1. Decrement previous owner's chat count
        if from_agent:
            decrement_agent_chat_count(from_agent)
            logger.info(
                "ticket_reassignment_decremented_from_agent",
                ticket_id=hubspot_ticket_id,
                agent=from_agent.name,
                new_count=from_agent.current_simultaneous_chats,
            )

        # 2. Increment new owner's chat count (if assigned to someone)
        if to_agent:
            increment_agent_chat_count(to_agent)
            logger.info(
                "ticket_reassignment_incremented_to_agent",
                ticket_id=hubspot_ticket_id,
                agent=to_agent.name,
                new_count=to_agent.current_simultaneous_chats,
            )

        # 3. Update AssignedConversation record
        if assigned_conv:
            if to_agent:
                assigned_conv.agent = to_agent
                assigned_conv.hubspot_owner_id = to_agent.hubspot_owner_id
                assigned_conv.agent_name = to_agent.name
            else:
                # Ticket was unassigned
                assigned_conv.agent = None
                assigned_conv.hubspot_owner_id = int(new_owner) if new_owner else None
                assigned_conv.agent_name = ""
            assigned_conv.save(update_fields=["agent", "hubspot_owner_id", "agent_name", "updated_at"])

        # 4. Log the reassignment for metrics
        ConversationReassignment.objects.create(
            hubspot_ticket_id=hubspot_ticket_id,
            from_agent=from_agent,
            from_hubspot_owner_id=int(prev_owner) if prev_owner else None,
            from_agent_name=from_agent.name if from_agent else None,
            to_agent=to_agent,
            to_hubspot_owner_id=int(new_owner) if new_owner else None,
            to_agent_name=to_agent.name if to_agent else None,
            reassigned_at=now,
            time_with_previous_agent_seconds=time_with_prev_seconds,
            reassignment_source="hubspot_webhook",
        )

    logger.info(
        "ticket_reassignment_processed",
        ticket_id=hubspot_ticket_id,
        from_agent=from_agent.name if from_agent else prev_owner,
        to_agent=to_agent.name if to_agent else new_owner,
        time_with_prev_seconds=float(time_with_prev_seconds) if time_with_prev_seconds else None,
    )


def _handle_conversation_event(event_type: str, payload: dict) -> None:
    """Process HubSpot Conversations events (legacy).

    These events come from the HubSpot Conversations API and include:
      - conversation.creation
      - conversation.deletion
      - conversation.privacyDeletion
      - conversation.propertyChange
      - conversation.newMessage

    Currently logged for auditing; extend as needed for specific use cases.
    """
    object_id = str(payload.get("objectId", ""))
    logger.debug(
        "hubspot_conversation_event",
        event_type=event_type,
        object_id=object_id,
        message_id=payload.get("messageId"),
    )


def _handle_contact_event(event_type: str, payload: dict) -> None:
    """Process contact-related HubSpot events.

    Handles ``hs_availability_status`` property changes as a fallback mechanism.
    The primary agent availability sync is handled by the polling task
    ``task_poll_hubspot_agent_status`` which uses the HubSpot Users API.

    Note: HubSpot does not support ``user.propertyChange`` webhook subscriptions,
    so we rely on ``contact.propertyChange`` as a secondary sync mechanism.
    """
    object_id = str(payload.get("objectId", ""))
    property_name = payload.get("propertyName", "")
    property_value = payload.get("propertyValue", "")

    if event_type == "contact.propertyChange" and property_name == _PROP_AVAILABILITY:
        _handle_agent_availability_change(object_id, property_value, payload)
    else:
        logger.debug("hubspot_contact_event", event_type=event_type, object_id=object_id)


def _handle_agent_availability_change(
    hubspot_contact_id: str,
    availability_value: str,
    payload: dict,
) -> None:
    """Update agent status_enum when HubSpot availability changes via webhook.

    Fallback handler for ``contact.propertyChange`` events. The primary sync
    mechanism is the polling task ``task_poll_hubspot_agent_status``.

    Mapping:
      ``"available"``  →  ``status_enum = "online"``
      ``"away"`` / other  →  ``status_enum = "away"``
    """
    new_status = "online" if availability_value == "available" else "away"

    # The payload may carry the email directly in changeSource context or
    # portalId; try to get it from known payload fields first.
    email = (payload.get("email") or "").lower().strip()

    if not email:
        # The webhook objectId is a HubSpot contact ID (not owner ID).
        # Use the Contacts API to resolve the agent's email.
        try:
            from apps.integrations.hubspot.client import get_hubspot_client

            client = get_hubspot_client()
            contact_details = client.get_contact_by_id(hubspot_contact_id)
            email = (contact_details.get("email") or "").lower().strip()
        except Exception as exc:
            logger.warning(
                "agent_availability_email_lookup_failed",
                contact_id=hubspot_contact_id,
                error=str(exc),
            )

    if not email:
        logger.warning(
            "agent_availability_change_no_email",
            contact_id=hubspot_contact_id,
            availability=availability_value,
        )
        return

    _update_agent_status_and_assign(email, new_status, availability_value, "hubspot_webhook")


def _update_agent_status_and_assign(
    email: str,
    new_status: str,
    availability_value: str,
    sync_source: str,
) -> None:
    """Update agent status and trigger pending ticket assignment if agent came online.

    Shared logic for both user.propertyChange and contact.propertyChange handlers.

    Args:
        email: Agent's email address.
        new_status: New status_enum value ("online" or "away").
        availability_value: Original HubSpot availability value for logging.
        sync_source: Source identifier for AgentStatusHistory.
    """
    from django.utils import timezone

    from apps.support.models import Agent, AgentStatusHistory

    agent = Agent.objects.filter(agent_email__iexact=email).exclude(is_active=False).first()
    if agent is None:
        logger.debug(
            "agent_not_found_for_availability_change",
            email=email,
        )
        return

    old_status = agent.status_enum
    status_changed = old_status != new_status
    if status_changed:
        agent.status_enum = new_status
        agent.updated_at = timezone.now()
        agent.save(update_fields=["status_enum", "updated_at"])

        AgentStatusHistory.objects.create(
            agent=agent,
            old_status=old_status,
            new_status=new_status,
            sync_source=sync_source,
        )

        logger.info(
            "agent_status_updated_via_webhook",
            agent=agent.name,
            email=email,
            old_status=old_status,
            new_status=new_status,
            availability=availability_value,
        )
    else:
        logger.debug(
            "agent_status_unchanged_via_webhook",
            agent=agent.name,
            status=new_status,
        )

    # When an agent just came online, drain any pending tickets from the queue
    # so they are assigned immediately rather than waiting for the next webhook.
    if status_changed and new_status == "online":
        try:
            from apps.support.auto_assign_service import assign_pending_tickets

            assign_result = assign_pending_tickets()
            logger.info(
                "agent_online_pending_assignment_triggered",
                agent=agent.name,
                **assign_result,
            )
        except Exception as assign_exc:
            logger.warning(
                "agent_online_pending_assignment_failed",
                agent=agent.name,
                error=str(assign_exc),
            )
