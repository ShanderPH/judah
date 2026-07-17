"""Unit tests for typed HubSpot ticket and user availability contracts."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from hubspot.crm.tickets.exceptions import ApiException, NotFoundException

from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotResourceNotFoundError


def test_users_api_requests_all_authoritative_availability_properties() -> None:
    cache.clear()
    client = HubSpotClient("test-token")
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "id": "user-1",
                "properties": {
                    "hs_email": "agent@example.com",
                    "hs_availability_status": "",
                    "hs_out_of_office_hours": "[]",
                    "hs_working_hours": "[]",
                    "hs_standard_time_zone": "America/Sao_Paulo",
                },
            }
        ]
    }

    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        return_value=response,
    ) as request:
        users = client.get_all_owners_availability()

    assert users[0]["availability_status"] == ""
    assert users[0]["status_enum"] == "away"
    _, url = request.call_args.args[:2]
    properties = request.call_args.kwargs["params"]["properties"]
    assert url.endswith("/crm/objects/2026-03/users")
    assert "hs_availability_status" in properties
    assert "hs_out_of_office_hours" in properties
    assert "hs_working_hours" in properties
    assert "hs_standard_time_zone" in properties


def test_assignment_critical_users_read_bypasses_cached_availability() -> None:
    cache.set(
        "hubspot_users_availability_2026_03",
        [{"user_id": "user-1", "availability_status": "available"}],
        timeout=15,
    )
    client = HubSpotClient("test-token")
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "id": "user-1",
                "properties": {
                    "hs_email": "agent@example.com",
                    "hs_availability_status": "away",
                    "hs_out_of_office_hours": "[]",
                    "hs_working_hours": "[]",
                    "hs_standard_time_zone": "America/Sao_Paulo",
                },
            }
        ]
    }

    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call",
        return_value=response,
    ) as request:
        users = client.get_all_owners_availability(force_refresh=True)

    request.assert_called_once()
    assert users[0]["availability_status"] == "away"
    assert users[0]["status_enum"] == "away"


def test_assign_ticket_owner_maps_not_found_to_permanent_error() -> None:
    client = HubSpotClient("test-token")

    with (
        patch(
            "apps.integrations.hubspot.client._circuit_breaker.call",
            side_effect=NotFoundException(status=404, reason="Not Found"),
        ),
        pytest.raises(HubSpotResourceNotFoundError) as captured,
    ):
        client.assign_ticket_owner("missing-ticket", 123)

    assert captured.value.external_status == 404
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (403, False), (429, True), (500, True), (503, True)],
)
def test_assign_ticket_owner_preserves_api_status(status: int, retryable: bool) -> None:
    client = HubSpotClient("test-token")

    with (
        patch(
            "apps.integrations.hubspot.client._circuit_breaker.call",
            side_effect=ApiException(status=status, reason="provider response"),
        ),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        client.assign_ticket_owner("ticket", 123)

    assert captured.value.external_status == status
    assert captured.value.retryable is retryable
