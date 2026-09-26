"""CRM stage-entry timestamps are normalized before domain consumers see them."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.integrations.hubspot.client import STAGE_CLOSED_ID, STAGE_NOVO_ID, HubSpotClient
from common.exceptions import ExternalServiceError


def test_ticket_details_normalizes_crm_iso_stage_entries() -> None:
    ticket = SimpleNamespace(
        id="close-ticket",
        properties={
            f"hs_v2_date_entered_{STAGE_NOVO_ID}": "2026-09-26T12:04:38.221Z",
            f"hs_v2_date_entered_{STAGE_CLOSED_ID}": "2026-09-26T16:08:57.952Z",
        },
        updated_at=datetime(2026, 9, 26, 16, 9, tzinfo=UTC),
        archived=False,
    )
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", return_value=ticket):
        details = HubSpotClient("test-token").get_ticket_details("close-ticket")

    assert details["entered_novo_at"] == datetime(2026, 9, 26, 12, 4, 38, 221000, tzinfo=UTC)
    assert details["entered_closed_at"] == datetime(2026, 9, 26, 16, 8, 57, 952000, tzinfo=UTC)


@pytest.mark.parametrize("invalid", ["2026-09-26T12:04:38.221", "invalid"])
def test_ticket_details_rejects_unprovable_crm_stage_entry(invalid: str) -> None:
    ticket = SimpleNamespace(
        id="close-ticket",
        properties={f"hs_v2_date_entered_{STAGE_NOVO_ID}": invalid},
        updated_at=None,
        archived=False,
    )
    with (
        patch("apps.integrations.hubspot.client._circuit_breaker.call", return_value=ticket),
        pytest.raises(ExternalServiceError),
    ):
        HubSpotClient("test-token").get_ticket_details("close-ticket")


def test_novo_search_normalizes_crm_iso_stage_entry() -> None:
    response = Mock()
    response.json.return_value = {
        "results": [
            {
                "id": "close-ticket",
                "properties": {f"hs_v2_date_entered_{STAGE_NOVO_ID}": "2026-09-26T12:04:38.221Z"},
            }
        ]
    }
    with patch("apps.integrations.hubspot.client._circuit_breaker.call", return_value=response):
        tickets = HubSpotClient("test-token").search_tickets_in_novo_stage()

    assert tickets[0]["entered_novo_at"] == datetime(2026, 9, 26, 12, 4, 38, 221000, tzinfo=UTC)
