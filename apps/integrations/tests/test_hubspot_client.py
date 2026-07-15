"""Unit tests for typed HubSpot ticket assignment failures."""

from unittest.mock import patch

import pytest
from hubspot.crm.tickets.exceptions import ApiException, NotFoundException

from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotResourceNotFoundError


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
