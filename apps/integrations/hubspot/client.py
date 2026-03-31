"""HubSpot API client for JUDAH."""

from typing import Any

import structlog
from hubspot import HubSpot
from hubspot.crm.tickets import SimplePublicObjectInputForCreate as TicketInput

from common.circuit_breaker import CircuitBreaker
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_circuit_breaker = CircuitBreaker(name="hubspot", failure_threshold=5, recovery_timeout=60)


class HubSpotClient:
    """Typed wrapper for the HubSpot API covering tickets, contacts, and conversations."""

    def __init__(self, access_token: str) -> None:
        self._client = HubSpot(access_token=access_token)

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Fetch a HubSpot ticket by its ID.

        Args:
            ticket_id: The numeric HubSpot ticket ID.

        Returns:
            Dict with ticket properties.

        Raises:
            ExternalServiceError: On API failure.
        """
        try:
            ticket = _circuit_breaker.call(
                self._client.crm.tickets.basic_api.get_by_id,
                ticket_id,
                properties=["subject", "hs_ticket_priority", "hs_pipeline_stage", "hubspot_owner_id"],
            )
            return {
                "id": ticket.id,
                "subject": ticket.properties.get("subject", ""),
                "priority": ticket.properties.get("hs_ticket_priority", ""),
                "stage": ticket.properties.get("hs_pipeline_stage", ""),
                "owner_id": ticket.properties.get("hubspot_owner_id", ""),
            }
        except Exception as exc:
            logger.error("hubspot_get_ticket_failed", ticket_id=ticket_id, error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def search_contact_by_email(self, email: str) -> dict[str, Any]:
        """Search for a HubSpot contact by email address.

        Args:
            email: The contact email to search for.

        Returns:
            Dict with contact properties or empty dict if not found.
        """
        try:
            from hubspot.crm.contacts import PublicObjectSearchRequest

            search_request = PublicObjectSearchRequest(
                filter_groups=[{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
                properties=["firstname", "lastname", "company", "lifecyclestage"],
            )
            response = _circuit_breaker.call(
                self._client.crm.contacts.search_api.do_search,
                public_object_search_request=search_request,
            )
            if response.results:
                contact = response.results[0]
                return {
                    "id": contact.id,
                    "firstname": contact.properties.get("firstname", ""),
                    "lastname": contact.properties.get("lastname", ""),
                    "company": contact.properties.get("company", ""),
                    "lifecycle_stage": contact.properties.get("lifecyclestage", ""),
                }
            return {}
        except Exception as exc:
            logger.error("hubspot_search_contact_failed", email=email, error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def create_ticket(self, subject: str, priority: str = "MEDIUM", pipeline: str = "0") -> dict[str, Any]:
        """Create a new HubSpot support ticket.

        Args:
            subject: Ticket subject/title.
            priority: Ticket priority (LOW, MEDIUM, HIGH, URGENT).
            pipeline: Pipeline ID (default "0" for default pipeline).

        Returns:
            Dict with created ticket id.
        """
        try:
            ticket_input = TicketInput(
                properties={
                    "subject": subject,
                    "hs_ticket_priority": priority.upper(),
                    "hs_pipeline": pipeline,
                    "hs_pipeline_stage": "1",
                }
            )
            ticket = _circuit_breaker.call(
                self._client.crm.tickets.basic_api.create,
                simple_public_object_input_for_create=ticket_input,
            )
            logger.info("hubspot_ticket_created", ticket_id=ticket.id)
            return {"id": ticket.id, "subject": subject}
        except Exception as exc:
            logger.error("hubspot_create_ticket_failed", subject=subject, error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc


_hubspot_client: HubSpotClient | None = None


def get_hubspot_client() -> HubSpotClient:
    """Return a shared HubSpotClient instance (singleton).

    Returns:
        Configured HubSpotClient.
    """
    global _hubspot_client
    if _hubspot_client is None:
        from django.conf import settings

        token = settings.HUBSPOT_ACCESS_TOKEN
        if not token:
            raise ValueError("HUBSPOT_ACCESS_TOKEN must be set.")
        _hubspot_client = HubSpotClient(access_token=token)
        logger.info("hubspot_client_initialized")
    return _hubspot_client
