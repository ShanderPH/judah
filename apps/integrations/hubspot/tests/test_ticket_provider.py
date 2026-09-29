"""Pinned CRM ticket contract and typed transport failures."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import HubSpotAPIError
from apps.integrations.hubspot.platform_contract import HubSpotTransport
from apps.integrations.hubspot.ticket_provider import HubSpotTicketProvider


def test_versioned_ticket_read_maps_stage_times_and_archived_fallback() -> None:
    """Ticket reads must map stage times and retry archived records."""
    transport = Mock()
    transport.get_json.side_effect = [
        HubSpotAPIError("not found", external_status=404, retryable=False),
        {
            "id": "42",
            "updatedAt": "2026-09-28T12:00:00Z",
            "archived": True,
            "properties": {
                "hs_pipeline": "11",
                "hs_pipeline_stage": "closed",
                "hubspot_owner_id": "77",
                "hs_v2_date_entered_1": "2026-09-28T10:00:00Z",
                "hs_v2_date_entered_2": "2026-09-28T11:00:00Z",
            },
        },
    ]
    provider = HubSpotTicketProvider(transport, new_stage_id="1", closed_stage_id="2")
    result = provider.get_details("42", ["hs_pipeline"])
    assert result["entered_closed_at"] == datetime(2026, 9, 28, 11, tzinfo=UTC)
    assert result["archived"] is True
    assert transport.get_json.call_args_list[0].args[0] == "/crm/objects/2026-09/tickets/42"
    assert transport.get_json.call_args_list[1].kwargs["params"]["archived"] == "true"


def test_versioned_ticket_write_patches_only_owner() -> None:
    """Owner updates must patch only the owner property."""
    transport = Mock()
    transport.patch_json.return_value = {"id": "42"}
    provider = HubSpotTicketProvider(transport, new_stage_id="1", closed_stage_id="2")
    assert provider.assign_owner("42", 77) == {"id": "42", "owner_id": 77}
    transport.patch_json.assert_called_once_with(
        "/crm/objects/2026-09/tickets/42", {"properties": {"hubspot_owner_id": "77"}}
    )


def test_client_enforce_mode_routes_ticket_read_to_versioned_adapter(settings) -> None:
    """Enforcement must route ticket reads through the versioned adapter."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    client = HubSpotClient.__new__(HubSpotClient)
    client._access_token = "test-token"
    client._client = Mock()
    with patch("apps.integrations.hubspot.platform_contract.HubSpotTransport") as transport_class:
        transport_class.return_value.get_json.return_value = {
            "id": "42",
            "updatedAt": "2026-09-28T12:00:00Z",
            "properties": {
                "hs_pipeline": "11",
                "hs_pipeline_stage": "new",
            },
        }
        assert client.get_ticket_details("42")["stage"] == "new"
    client._client.crm.tickets.basic_api.get_by_id.assert_not_called()


@pytest.mark.parametrize("status, retryable", [(401, False), (403, False), (429, True), (503, True)])
def test_transport_preserves_http_status(status: int, retryable: bool) -> None:
    """Transport failures must preserve the provider HTTP status."""
    response = Mock(status_code=status)
    with (
        patch("apps.integrations.hubspot.platform_contract.requests.request", return_value=response),
        pytest.raises(HubSpotAPIError) as error,
    ):
        HubSpotTransport("test-token").get_json("/crm/objects/2026-09/tickets", params={"limit": 1})
    assert error.value.external_status == status
    assert error.value.retryable is retryable
