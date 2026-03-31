"""Agno tools for querying HubSpot CRM data."""

from typing import Any

import structlog
from agno.tools import Toolkit

logger = structlog.get_logger(__name__)


class GetTicketInfo(Toolkit):
    """Retrieve ticket and contact information from HubSpot."""

    def __init__(self) -> None:
        super().__init__(name="hubspot_tools")
        self.register(self.get_ticket)
        self.register(self.search_contact)

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Fetch details for a HubSpot ticket by its ID.

        Args:
            ticket_id: The HubSpot ticket ID.

        Returns:
            Dict with ticket subject, status, priority, and owner.
        """
        try:
            from apps.integrations.hubspot.client import get_hubspot_client

            client = get_hubspot_client()
            return client.get_ticket(ticket_id)
        except Exception as exc:
            logger.error("hubspot_get_ticket_failed", ticket_id=ticket_id, error=str(exc))
            return {"error": str(exc)}

    def search_contact(self, email: str) -> dict[str, Any]:
        """Look up a HubSpot contact by email address.

        Args:
            email: The contact's email address.

        Returns:
            Dict with contact name, company, and lifecycle stage.
        """
        try:
            from apps.integrations.hubspot.client import get_hubspot_client

            client = get_hubspot_client()
            return client.search_contact_by_email(email)
        except Exception as exc:
            logger.error("hubspot_search_contact_failed", email=email, error=str(exc))
            return {"error": str(exc)}
