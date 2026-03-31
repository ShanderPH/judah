"""HubSpot integration service layer."""

import structlog

from apps.integrations.hubspot.client import get_hubspot_client

logger = structlog.get_logger(__name__)


def sync_ticket_to_hubspot(ticket_id: int) -> str | None:
    """Sync a local support ticket to HubSpot.

    Args:
        ticket_id: Local Ticket primary key.

    Returns:
        HubSpot ticket ID if created successfully, else None.
    """
    from apps.support.models import Ticket

    try:
        ticket = Ticket.objects.get(pk=ticket_id)
        client = get_hubspot_client()
        result = client.create_ticket(
            subject=ticket.subject,
            priority=ticket.priority.upper(),
        )
        ticket.hubspot_ticket_id = result["id"]
        ticket.save(update_fields=["hubspot_ticket_id", "updated_at"])
        logger.info("ticket_synced_to_hubspot", ticket_id=ticket_id, hubspot_id=result["id"])
        return result["id"]
    except Exception as exc:
        logger.error("ticket_sync_to_hubspot_failed", ticket_id=ticket_id, error=str(exc))
        return None
