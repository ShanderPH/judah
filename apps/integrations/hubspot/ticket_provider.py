"""Pinned HubSpot CRM ticket read and owner-write adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from apps.integrations.hubspot.exceptions import HubSpotAPIError
from apps.integrations.hubspot.platform_contract import HubSpotTransport


def _stage_time(value: object) -> datetime | None:
    """Parse an aware HubSpot stage timestamp into UTC."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise HubSpotAPIError("Invalid ticket stage timestamp.", retryable=False)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HubSpotAPIError("Invalid ticket stage timestamp.", retryable=False) from exc
    if parsed.tzinfo is None:
        raise HubSpotAPIError("Ticket stage timestamp lacks a timezone.", retryable=False)
    return parsed.astimezone(UTC)


class HubSpotTicketProvider:
    """Translate Tickets 2026-09 JSON without support-domain decisions."""

    def __init__(self, transport: HubSpotTransport, *, new_stage_id: str, closed_stage_id: str) -> None:
        self.transport = transport
        self.new_stage_id = new_stage_id
        self.closed_stage_id = closed_stage_id

    @staticmethod
    def _path(ticket_id: str) -> str:
        """Build a ticket path after validating its numeric identifier."""
        if not ticket_id.isdigit():
            raise ValueError("HubSpot ticket ID must be numeric")
        return f"/crm/objects/2026-09/tickets/{quote(ticket_id, safe='')}"

    def get_details(self, ticket_id: str, properties: list[str]) -> dict[str, Any]:
        """Read one ticket, checking the archived representation after a 404."""
        path = self._path(ticket_id)
        params = {"properties": ",".join(properties)}
        try:
            body = self.transport.get_json(path, params=params)
        except HubSpotAPIError as exc:
            if exc.external_status != 404:
                raise
            body = self.transport.get_json(path, params={**params, "archived": "true"})
        props = body.get("properties")
        if not isinstance(props, dict) or str(body.get("id")) != ticket_id:
            raise HubSpotAPIError("Invalid ticket response.", retryable=False)
        updated_at = body.get("updatedAt")
        if updated_at and not isinstance(updated_at, str):
            raise HubSpotAPIError("Invalid ticket update timestamp.", retryable=False)
        return {
            "id": ticket_id,
            "subject": props.get("subject", ""),
            "priority": props.get("hs_ticket_priority", ""),
            "pipeline": props.get("hs_pipeline", ""),
            "stage": props.get("hs_pipeline_stage", ""),
            "owner_id": props.get("hubspot_owner_id") or "",
            "entered_novo_at": _stage_time(props.get(f"hs_v2_date_entered_{self.new_stage_id}")),
            "entered_closed_at": _stage_time(props.get(f"hs_v2_date_entered_{self.closed_stage_id}")),
            "contact_name": props.get("firstname", ""),
            "contact_email": props.get("email", ""),
            "updated_at": updated_at,
            "archived": body.get("archived", False),
        }

    def assign_owner(self, ticket_id: str, owner_id: int) -> dict[str, Any]:
        """Patch only the CRM owner property and verify the returned identity."""
        body = self.transport.patch_json(self._path(ticket_id), {"properties": {"hubspot_owner_id": str(owner_id)}})
        if str(body.get("id")) != ticket_id:
            raise HubSpotAPIError("Ticket owner write returned a different ticket.", retryable=False)
        return {"id": ticket_id, "owner_id": owner_id}
