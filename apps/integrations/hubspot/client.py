"""HubSpot API client for JUDAH."""

from __future__ import annotations

from typing import Any

import structlog
from hubspot import HubSpot
from hubspot.crm.tickets import SimplePublicObjectInput as TicketUpdateInput
from hubspot.crm.tickets import SimplePublicObjectInputForCreate as TicketInput

from common.circuit_breaker import CircuitBreaker
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_circuit_breaker = CircuitBreaker(name="hubspot", failure_threshold=5, recovery_timeout=60)

# Pipeline constants
SUPPORT_PIPELINE_ID = "636459134"
STAGE_NOVO_ID = "939275049"
STAGE_CLOSED_ID = "939275052"

# HubSpot team IDs for N1 support
HUBSPOT_TEAM_N1_ID = "8"  # 8.1 N1 sub-team
HUBSPOT_TEAM_SUPORTE_ID = "8"  # 08. Suporte parent team


class HubSpotClient:
    """Typed wrapper for the HubSpot API covering tickets, contacts, and conversations."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
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

    def get_contact_by_id(self, contact_id: str) -> dict[str, Any]:
        """Fetch a HubSpot contact by contact ID to retrieve their email.

        Used when a ``contact.propertyChange`` webhook arrives: the payload
        ``objectId`` is a contact ID, not an owner ID, so we need the Contacts
        API to resolve the email before looking up the matching local agent.

        Args:
            contact_id: The HubSpot contact ID (from webhook ``objectId``).

        Returns:
            Dict with ``id``, ``email``, ``firstname``, ``lastname`` keys,
            or an empty dict if the contact is not found.
        """
        try:
            contact = _circuit_breaker.call(
                self._client.crm.contacts.basic_api.get_by_id,
                contact_id,
                properties=["email", "firstname", "lastname"],
            )
            props = contact.properties or {}
            return {
                "id": contact.id,
                "email": props.get("email", ""),
                "firstname": props.get("firstname", ""),
                "lastname": props.get("lastname", ""),
            }
        except Exception as exc:
            logger.warning("hubspot_get_contact_by_id_failed", contact_id=contact_id, error=str(exc))
            return {}

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

    def get_ticket_details(self, ticket_id: str, properties: list[str] | None = None) -> dict[str, Any]:
        """Fetch a HubSpot ticket with extended properties for assignment validation.

        Args:
            ticket_id: The numeric HubSpot ticket ID.
            properties: List of property names to fetch. Defaults to assignment-relevant set.

        Returns:
            Dict with ticket properties.

        Raises:
            ExternalServiceError: On API failure.
        """
        default_props = [
            "subject",
            "hs_ticket_priority",
            "hs_pipeline",
            "hs_pipeline_stage",
            "hubspot_owner_id",
            "hs_v2_date_entered_939275049",
            "hs_v2_date_entered_939275052",
            "hs_lastcontacted",
            "firstname",
            "email",
        ]
        fetch_props = properties or default_props
        try:
            ticket = _circuit_breaker.call(
                self._client.crm.tickets.basic_api.get_by_id,
                ticket_id,
                properties=fetch_props,
            )
            props = ticket.properties or {}
            return {
                "id": ticket.id,
                "subject": props.get("subject", ""),
                "priority": props.get("hs_ticket_priority", ""),
                "pipeline": props.get("hs_pipeline", ""),
                "stage": props.get("hs_pipeline_stage", ""),
                "owner_id": props.get("hubspot_owner_id") or "",
                "contact_name": props.get("firstname", ""),
                "contact_email": props.get("email", ""),
            }
        except Exception as exc:
            logger.error("hubspot_get_ticket_details_failed", ticket_id=ticket_id, error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def assign_ticket_owner(self, ticket_id: str, owner_id: int) -> dict[str, Any]:
        """Assign a HubSpot ticket to an owner (agent) by their owner ID.

        This is the authoritative way to assign a ticket via HubSpot CRM API.
        It updates the ``hubspot_owner_id`` property of the ticket.

        Args:
            ticket_id: The numeric HubSpot ticket ID.
            owner_id: The HubSpot owner ID of the agent to assign.

        Returns:
            Dict with updated ticket id and owner_id.

        Raises:
            ExternalServiceError: On API failure.
        """
        try:
            update_input = TicketUpdateInput(properties={"hubspot_owner_id": str(owner_id)})
            ticket = _circuit_breaker.call(
                self._client.crm.tickets.basic_api.update,
                ticket_id,
                simple_public_object_input=update_input,
            )
            logger.info("hubspot_ticket_owner_assigned", ticket_id=ticket_id, owner_id=owner_id)
            return {
                "id": ticket.id,
                "owner_id": owner_id,
            }
        except Exception as exc:
            logger.error(
                "hubspot_assign_ticket_owner_failed",
                ticket_id=ticket_id,
                owner_id=owner_id,
                error=str(exc),
            )
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def get_owner_details(self, owner_id: int) -> dict[str, Any]:
        """Fetch owner details by owner ID.

        Args:
            owner_id: The HubSpot owner ID.

        Returns:
            Dict with owner properties or empty dict if not found.
        """
        try:
            owner = _circuit_breaker.call(
                self._client.crm.owners.owners_api.get_by_id,
                owner_id=owner_id,
            )
            return {
                "id": owner.id,
                "email": getattr(owner, "email", ""),
                "first_name": getattr(owner, "first_name", ""),
                "last_name": getattr(owner, "last_name", ""),
                "user_id": getattr(owner, "user_id", None),
                "teams": [{"id": t.id, "name": t.name} for t in (getattr(owner, "teams", None) or [])],
            }
        except Exception as exc:
            logger.warning("hubspot_get_owner_details_failed", owner_id=owner_id, error=str(exc))
            return {}

    def get_team_members(self, team_id: str) -> list[dict[str, Any]]:
        """Fetch all owners that belong to a HubSpot team.

        Args:
            team_id: The HubSpot team ID.

        Returns:
            List of owner dicts with id, email, first_name, last_name.
        """
        try:
            result = _circuit_breaker.call(
                self._client.crm.owners.owners_api.get_page,
                limit=100,
            )
            members = []
            for owner in result.results or []:
                owner_teams = getattr(owner, "teams", None) or []
                if any(str(getattr(t, "id", "")) == str(team_id) for t in owner_teams):
                    members.append(
                        {
                            "id": owner.id,
                            "email": getattr(owner, "email", ""),
                            "first_name": getattr(owner, "first_name", ""),
                            "last_name": getattr(owner, "last_name", ""),
                        }
                    )
            logger.info("hubspot_team_members_fetched", team_id=team_id, count=len(members))
            return members
        except Exception as exc:
            logger.error("hubspot_get_team_members_failed", team_id=team_id, error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def search_tickets_in_novo_stage(self) -> list[dict[str, Any]]:
        """Fetch all tickets in the NOVO stage of the support pipeline.

        Uses the HubSpot Tickets Search API with full pagination to return
        every ticket in pipeline ``636459134`` / stage ``939275049`` regardless
        of whether they have an owner.

        Returns:
            List of ticket dicts with ``id``, ``subject``, ``priority``,
            ``pipeline``, ``stage``, ``owner_id``, ``contact_name``,
            ``contact_email``, ``entered_novo_at`` keys.

        Raises:
            ExternalServiceError: On API failure.
        """
        import requests as _requests

        try:
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            url = "https://api.hubapi.com/crm/v3/objects/tickets/search"
            properties = [
                "subject",
                "hs_ticket_priority",
                "hs_pipeline",
                "hs_pipeline_stage",
                "hubspot_owner_id",
                f"hs_v2_date_entered_{STAGE_NOVO_ID}",
                "firstname",
                "email",
            ]
            body = {
                "filterGroups": [
                    {
                        "filters": [
                            {"propertyName": "hs_pipeline", "operator": "EQ", "value": SUPPORT_PIPELINE_ID},
                            {"propertyName": "hs_pipeline_stage", "operator": "EQ", "value": STAGE_NOVO_ID},
                        ]
                    }
                ],
                "properties": properties,
                "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
                "limit": 100,
            }

            results: list[dict[str, Any]] = []
            after: str | None = None

            while True:
                if after:
                    body["after"] = after

                response = _circuit_breaker.call(
                    _requests.post,
                    url,
                    json=body,
                    headers=headers,
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()

                for ticket in data.get("results", []):
                    props = ticket.get("properties") or {}
                    results.append(
                        {
                            "id": ticket["id"],
                            "subject": props.get("subject", ""),
                            "priority": props.get("hs_ticket_priority", ""),
                            "pipeline": props.get("hs_pipeline", ""),
                            "stage": props.get("hs_pipeline_stage", ""),
                            "owner_id": props.get("hubspot_owner_id") or "",
                            "contact_name": props.get("firstname", ""),
                            "contact_email": props.get("email", ""),
                            "entered_novo_at": props.get(f"hs_v2_date_entered_{STAGE_NOVO_ID}"),
                        }
                    )

                paging = data.get("paging", {})
                next_page = paging.get("next", {})
                after = next_page.get("after")
                if not after:
                    break

            logger.info("hubspot_novo_tickets_fetched", count=len(results))
            return results

        except Exception as exc:
            logger.error("hubspot_search_novo_tickets_failed", error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def get_user_by_id(self, user_id: str) -> dict[str, Any]:
        """Fetch a HubSpot User by their User ID (hs_object_id).

        Uses the CRM Users API (``GET /crm/v3/objects/users/{userId}``) to
        retrieve user details including email and availability status.

        Args:
            user_id: The HubSpot User ID (hs_object_id from webhook payload).

        Returns:
            Dict with ``id``, ``email``, ``hs_availability_status`` keys,
            or an empty dict if the user is not found.
        """
        import requests

        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            response = _circuit_breaker.call(
                requests.get,
                f"https://api.hubapi.com/crm/v3/objects/users/{user_id}",
                headers=headers,
                params={"properties": "hs_email,hs_availability_status"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            props = data.get("properties") or {}
            return {
                "id": data.get("id"),
                "email": props.get("hs_email", ""),
                "hs_availability_status": props.get("hs_availability_status", ""),
            }
        except Exception as exc:
            logger.warning("hubspot_get_user_by_id_failed", user_id=user_id, error=str(exc))
            return {}

    def get_all_owners_availability(self) -> list[dict[str, Any]]:
        """Fetch all HubSpot users with their current availability status.

        Uses the HubSpot CRM Users API (``GET /crm/v3/objects/users``) which
        exposes the ``hs_availability_status`` property:
          - ``"available"`` → mapped to ``"online"``
          - ``"away"`` / anything else → mapped to ``"away"``

        Returns:
            List of dicts with ``user_id``, ``email``, ``availability_status``,
            ``status_enum`` keys.

        Raises:
            ExternalServiceError: On API failure.
        """
        import requests

        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            response = _circuit_breaker.call(
                requests.get,
                "https://api.hubapi.com/crm/v3/objects/users",
                headers=headers,
                params={
                    "limit": 100,
                    "properties": "hs_email,hs_availability_status",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            result = []
            for user in data.get("results", []):
                props = user.get("properties") or {}
                availability = props.get("hs_availability_status") or "available"
                result.append(
                    {
                        "user_id": user.get("id"),
                        "email": props.get("hs_email", ""),
                        "availability_status": availability,
                        "status_enum": "online" if availability == "available" else "away",
                    }
                )
            logger.info("hubspot_owners_availability_fetched", count=len(result))
            return result
        except Exception as exc:
            logger.error("hubspot_get_owners_availability_failed", error=str(exc))
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
