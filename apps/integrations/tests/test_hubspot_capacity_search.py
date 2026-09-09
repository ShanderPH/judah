"""Search discovery completeness and bounded request budget contracts."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from apps.integrations.hubspot.client import HubSpotClient


def response(data: dict) -> MagicMock:
    result = MagicMock()
    result.json.return_value = data
    return result


def test_paginated_ticket_ids_are_complete(settings):
    cache.clear()
    settings.SUPPORT_CAPACITY_MAX_SCAN_TICKETS = 400
    pages = [
        response({"total": 2, "results": [{"id": "1"}], "paging": {"next": {"after": "abc"}}}),
        response({"total": 2, "results": [{"id": "2"}]}),
    ]
    with patch("requests.post", side_effect=pages) as request:
        assert HubSpotClient("test-placeholder").list_active_ticket_ids_by_owner(100) == (("1", "2"), True)
    assert request.call_args.kwargs["json"]["after"] == "abc"
    assert request.call_count == 2


@pytest.mark.parametrize(
    "data",
    [
        {"total": 2, "results": [{"id": "1"}]},
        {"total": 10001, "results": []},
        {"total": 1, "results": [{"id": "1"}, {"id": "1"}]},
        {"results": []},
    ],
)
def test_incomplete_or_malformed_search_is_never_ready(data):
    cache.clear()
    with patch("requests.post", return_value=response(data)):
        _, complete = HubSpotClient("test-placeholder").list_active_ticket_ids_by_owner(100)
    assert not complete


def test_search_http_failure_is_incomplete():
    cache.clear()
    with patch("requests.post", side_effect=TimeoutError):
        assert HubSpotClient("test-placeholder").list_active_ticket_ids_by_owner(100) == ((), False)


def test_archival_requires_positive_readback_after_not_found():
    from types import SimpleNamespace

    from hubspot.crm.tickets.exceptions import NotFoundException

    archived = SimpleNamespace(id="1", properties={"hs_pipeline": "support"}, archived=True, updated_at=None)
    with patch(
        "apps.integrations.hubspot.client._circuit_breaker.call", side_effect=[NotFoundException(), archived]
    ) as read:
        assert HubSpotClient("test-placeholder").get_ticket_details("1")["archived"] is True
    assert read.call_args.kwargs["archived"] is True
