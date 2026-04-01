"""Handler for HubSpot webhook events."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# HubSpot property names that trigger auto-assignment logic
_PROP_STAGE_NOVO = "hs_v2_date_entered_939275049"  # Ticket entered NOVO stage
_PROP_STAGE_CLOSED = "hs_v2_date_entered_939275052"  # Ticket entered FECHADO stage
_PROP_PIPELINE_STAGE = "hs_pipeline_stage"
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

    logger.info("hubspot_event_received", event_type=event_type, event_id=event.pk)

    if "ticket" in event_type.lower():
        _handle_ticket_event(event_type, payload)
    elif "contact" in event_type.lower():
        _handle_contact_event(event_type, payload)
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


def _handle_contact_event(event_type: str, payload: dict) -> None:
    """Process contact-related HubSpot events.

    Handles ``hs_availability_status`` property changes so that agent status
    in the local DB is updated instantly when an agent changes availability
    in HubSpot (requires the private app webhook to subscribe to
    ``contact.propertyChange`` → ``hs_availability_status``).
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

    Called when a ``contact.propertyChange`` event arrives for
    ``hs_availability_status``. Resolves the agent by matching the contact
    email from the payload (or by fetching from HubSpot if not present).

    Mapping:
      ``"available"``  →  ``status_enum = "online"``
      ``"away"`` / other  →  ``status_enum = "away"``
    """
    from apps.support.models import Agent

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

    try:
        agent = Agent.objects.get(agent_email__iexact=email, is_active=True)
        status_changed = agent.status_enum != new_status
        if status_changed:
            agent.status_enum = new_status
            agent.save(update_fields=["status_enum"])
            logger.info(
                "agent_status_updated_via_webhook",
                agent=agent.name,
                email=email,
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

    except Agent.DoesNotExist:
        logger.debug(
            "agent_not_found_for_availability_change",
            email=email,
            contact_id=hubspot_contact_id,
        )
    except Exception as exc:
        logger.error(
            "agent_availability_update_failed",
            email=email,
            error=str(exc),
        )
