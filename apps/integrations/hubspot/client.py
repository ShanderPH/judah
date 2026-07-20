"""HubSpot API client for JUDAH."""

from __future__ import annotations

from typing import Any

import structlog
from django.conf import settings
from hubspot import HubSpot
from hubspot.crm.tickets import SimplePublicObjectInput as TicketUpdateInput
from hubspot.crm.tickets import SimplePublicObjectInputForCreate as TicketInput
from hubspot.crm.tickets.exceptions import ApiException, NotFoundException

from apps.integrations.hubspot.exceptions import (
    HubSpotAPIError,
    HubSpotFailureKind,
    HubSpotResourceNotFoundError,
)
from common.circuit_breaker import CircuitBreaker
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)

_circuit_breaker = CircuitBreaker(
    name="hubspot",
    failure_threshold=5,
    recovery_timeout=60,
    excluded_exceptions=(NotFoundException,),
)

# Pipeline configuration is sourced from the environment through Django settings.
SUPPORT_PIPELINE_ID = settings.HUBSPOT_SUPPORT_PIPELINE_ID
STAGE_NOVO_ID = settings.HUBSPOT_SUPPORT_NEW_STAGE_ID
STAGE_CLOSED_ID = settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID
STAGE_FECHADO_ID = STAGE_CLOSED_ID  # Alias for Portuguese naming consistency

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

    def create_ticket(self, subject: str, priority: str = "MEDIUM", pipeline: str | None = None) -> dict[str, Any]:
        """Create a new HubSpot support ticket.

        Args:
            subject: Ticket subject/title.
            priority: Ticket priority (LOW, MEDIUM, HIGH, URGENT).
            pipeline: Pipeline ID. Uses ``HUBSPOT_DEFAULT_TICKET_PIPELINE_ID`` when omitted.

        Returns:
            Dict with created ticket id.
        """
        try:
            ticket_input = TicketInput(
                properties={
                    "subject": subject,
                    "hs_ticket_priority": priority.upper(),
                    "hs_pipeline": pipeline or settings.HUBSPOT_DEFAULT_TICKET_PIPELINE_ID,
                    "hs_pipeline_stage": settings.HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID,
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
            f"hs_v2_date_entered_{STAGE_NOVO_ID}",
            f"hs_v2_date_entered_{STAGE_CLOSED_ID}",
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
        except NotFoundException as exc:
            logger.warning(
                "hubspot_assign_ticket_owner_not_found",
                ticket_id=ticket_id,
                owner_id=owner_id,
                external_status=exc.status or 404,
            )
            raise HubSpotResourceNotFoundError("ticket", ticket_id) from exc
        except ApiException as exc:
            external_status = int(exc.status) if exc.status is not None else None
            retryable = external_status is None or external_status == 429 or external_status >= 500
            logger.error(
                "hubspot_assign_ticket_owner_failed",
                ticket_id=ticket_id,
                owner_id=owner_id,
                external_status=external_status,
                reason=exc.reason,
                retryable=retryable,
            )
            raise HubSpotAPIError(
                "HubSpot rejected the ticket owner update.",
                external_status=external_status,
                retryable=retryable,
                error_code=(
                    HubSpotFailureKind.RATE_LIMITED
                    if external_status == 429
                    else HubSpotFailureKind.SERVER_ERROR
                    if external_status is not None and external_status >= 500
                    else HubSpotFailureKind.UNAUTHORIZED
                    if external_status == 401
                    else HubSpotFailureKind.FORBIDDEN
                    if external_status == 403
                    else HubSpotFailureKind.UNKNOWN
                ),
            ) from exc
        except Exception as exc:
            logger.error(
                "hubspot_assign_ticket_owner_failed",
                ticket_id=ticket_id,
                owner_id=owner_id,
                error_type=type(exc).__name__,
                retryable=True,
            )
            raise HubSpotAPIError(
                "HubSpot ticket owner update failed.",
                retryable=True,
                error_code=HubSpotFailureKind.UNKNOWN,
            ) from exc

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
        every ticket in the configured support pipeline / NOVO stage regardless
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
        import random
        import time

        import requests

        headers = {"Authorization": f"Bearer {self._access_token}"}
        properties = ",".join(
            (
                "hs_email",
                "hs_availability_status",
                "hs_out_of_office_hours",
                "hs_working_hours",
                "hs_standard_time_zone",
            )
        )
        for attempt in range(3):
            try:
                response = _circuit_breaker.call(
                    requests.get,
                    f"https://api.hubapi.com/crm/objects/2026-03/users/{user_id}",
                    headers=headers,
                    params={"properties": properties},
                    timeout=10,
                )
            except requests.Timeout as exc:
                if attempt < 2:
                    time.sleep((0.1 * (2**attempt)) + random.uniform(0, 0.1))
                    continue
                raise HubSpotAPIError(
                    "HubSpot user lookup timed out.",
                    retryable=True,
                    error_code=HubSpotFailureKind.TIMEOUT,
                ) from exc
            except requests.RequestException as exc:
                raise HubSpotAPIError(
                    "HubSpot user lookup failed.",
                    retryable=True,
                    error_code=HubSpotFailureKind.UNKNOWN,
                ) from exc

            status = response.status_code
            retry_after_raw = response.headers.get("Retry-After")
            retry_after = (
                float(retry_after_raw) if retry_after_raw and retry_after_raw.replace(".", "", 1).isdigit() else None
            )
            if status == 404:
                raise HubSpotResourceNotFoundError("user", user_id)
            if status in (401, 403):
                kind = HubSpotFailureKind.UNAUTHORIZED if status == 401 else HubSpotFailureKind.FORBIDDEN
                raise HubSpotAPIError(
                    "HubSpot rejected the user lookup.",
                    external_status=status,
                    retryable=False,
                    error_code=kind,
                )
            if status == 429 or status >= 500:
                kind = HubSpotFailureKind.RATE_LIMITED if status == 429 else HubSpotFailureKind.SERVER_ERROR
                if attempt < 2:
                    delay = retry_after if retry_after is not None else 0.1 * (2**attempt)
                    time.sleep(min(delay, 2.0) + random.uniform(0, 0.1))
                    continue
                raise HubSpotAPIError(
                    "HubSpot user lookup is temporarily unavailable.",
                    external_status=status,
                    retryable=True,
                    error_code=kind,
                    retry_after_seconds=retry_after,
                )
            if not 200 <= status < 300:
                raise HubSpotAPIError(
                    "HubSpot rejected the user lookup.",
                    external_status=status,
                    retryable=False,
                    error_code=HubSpotFailureKind.UNKNOWN,
                )
            try:
                data = response.json()
                props = data["properties"]
                if not isinstance(props, dict) or not data.get("id"):
                    raise ValueError("missing user properties")
            except (TypeError, ValueError, KeyError) as exc:
                raise HubSpotAPIError(
                    "HubSpot returned a malformed user response.",
                    external_status=status,
                    retryable=False,
                    error_code=HubSpotFailureKind.MALFORMED_RESPONSE,
                ) from exc
            return {
                "id": data.get("id"),
                "email": props.get("hs_email", ""),
                "hs_availability_status": props.get("hs_availability_status", ""),
                "hs_out_of_office_hours": props.get("hs_out_of_office_hours"),
                "hs_working_hours": props.get("hs_working_hours"),
                "hs_standard_time_zone": props.get("hs_standard_time_zone", ""),
            }
        raise AssertionError("bounded HubSpot retry loop exhausted unexpectedly")

    def get_all_owners_availability(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch all HubSpot users with their current availability status.

        Uses the HubSpot CRM Users API (``GET /crm/v3/objects/users``) which
        exposes the ``hs_availability_status`` property:
          - ``"available"`` → mapped to ``"online"``
          - ``"away"`` / anything else → mapped to ``"away"``

        Paginates through ALL users using the ``after`` cursor to avoid the
        default 100-record limit. Portals with >100 users would silently miss
        agents on page 2+ without pagination.

        Results are cached in Redis for 15 seconds to avoid redundant API calls
        when periodic SAT heartbeats overlap. Assignment-critical reconciliation
        bypasses that cache so a ticket webhook never trusts an older snapshot.

        Args:
            force_refresh: Bypass the short-lived cache and read HubSpot now.

        Returns:
            List of dicts with ``user_id``, ``email``, ``availability_status``,
            ``status_enum`` keys.

        Raises:
            ExternalServiceError: On API failure.
        """
        import requests
        from django.core.cache import cache

        # Check cache first — avoids redundant API calls within the same
        # SAT heartbeat cycle (e.g. heartbeat + drain + reconcile overlap).
        cache_key = "hubspot_users_availability_2026_03"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug("hubspot_owners_availability_cache_hit", count=len(cached))
                return cached

        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            result = []
            after: str | None = None
            page = 0

            properties = ",".join(
                (
                    "hs_email",
                    "hs_availability_status",
                    "hs_out_of_office_hours",
                    "hs_working_hours",
                    "hs_standard_time_zone",
                )
            )

            while True:
                params: dict = {
                    "limit": 100,
                    "properties": properties,
                }
                if after:
                    params["after"] = after

                response = _circuit_breaker.call(
                    requests.get,
                    "https://api.hubapi.com/crm/objects/2026-03/users",
                    headers=headers,
                    params=params,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                page += 1

                for user in data.get("results", []):
                    props = user.get("properties") or {}
                    availability = str(props.get("hs_availability_status") or "").strip().lower()
                    result.append(
                        {
                            "user_id": user.get("id"),
                            "email": props.get("hs_email", ""),
                            "availability_status": availability,
                            "out_of_office_hours": props.get("hs_out_of_office_hours"),
                            "working_hours": props.get("hs_working_hours"),
                            "timezone": props.get("hs_standard_time_zone", ""),
                            "status_enum": "online" if availability == "available" else "away",
                        }
                    )

                # Follow pagination cursor; stop when no next page
                paging = data.get("paging") or {}
                after = (paging.get("next") or {}).get("after")
                if not after:
                    break

            # Cache for 15 seconds — shorter than the 20-second heartbeat interval
            # to ensure fresh data on the next cycle.
            cache.set(cache_key, result, timeout=15)

            logger.info("hubspot_owners_availability_fetched", count=len(result), pages=page)
            return result
        except Exception as exc:
            logger.error("hubspot_get_owners_availability_failed", error=str(exc))
            raise ExternalServiceError("HubSpot", str(exc)) from exc

    def count_active_tickets_by_owner(self, owner_id: int) -> int:
        """Count active (non-closed) tickets assigned to a specific owner.

        Uses the HubSpot Tickets Search API to count tickets in the support
        pipeline that are assigned to the given owner and are NOT in the
        FECHADO (closed) stage.

        Args:
            owner_id: The HubSpot owner ID.

        Returns:
            Number of active tickets assigned to this owner.
        """
        import requests

        try:
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "filterGroups": [
                    {
                        "filters": [
                            {"propertyName": "hs_pipeline", "operator": "EQ", "value": SUPPORT_PIPELINE_ID},
                            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": str(owner_id)},
                            {"propertyName": "hs_pipeline_stage", "operator": "NEQ", "value": STAGE_FECHADO_ID},
                        ]
                    }
                ],
                "limit": 1,
            }
            response = _circuit_breaker.call(
                requests.post,
                "https://api.hubapi.com/crm/v3/objects/tickets/search",
                headers=headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            count = data.get("total", 0)
            logger.debug("hubspot_active_tickets_count", owner_id=owner_id, count=count)
            return count
        except Exception as exc:
            logger.warning("hubspot_count_active_tickets_failed", owner_id=owner_id, error=str(exc))
            return -1  # Return -1 to indicate error; caller should handle gracefully


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
