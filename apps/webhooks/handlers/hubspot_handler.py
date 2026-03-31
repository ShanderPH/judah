"""Handler for HubSpot webhook events."""

import structlog

logger = structlog.get_logger(__name__)


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

    from apps.support.models import Ticket

    try:
        ticket = Ticket.objects.get(hubspot_ticket_id=object_id)
        if event_type == "ticket.propertyChange" and payload.get("propertyName") == "hs_pipeline_stage":
            new_stage = payload.get("propertyValue", "")
            if new_stage == "4":
                ticket.status = Ticket.Status.RESOLVED
                ticket.save(update_fields=["status", "updated_at"])
                logger.info("ticket_resolved_via_hubspot", ticket_id=ticket.pk)
    except Ticket.DoesNotExist:
        logger.debug("hubspot_ticket_not_synced", hubspot_id=object_id)


def _handle_contact_event(event_type: str, payload: dict) -> None:
    """Process contact-related HubSpot events."""
    logger.debug("hubspot_contact_event", event_type=event_type, object_id=payload.get("objectId"))
