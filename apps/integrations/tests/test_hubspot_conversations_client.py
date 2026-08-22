"""HubSpot Conversations API client coverage."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import HubSpotAPIError, HubSpotResourceNotFoundError


def _response(status: int, body=None, headers=None) -> Mock:
    response = Mock(status_code=status, headers=headers or {})
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = {} if body is None else body
    return response


@override_settings(
    HUBSPOT_CONVERSATIONS_MAX_ATTEMPTS=1,
    HUBSPOT_CONVERSATIONS_CONNECT_TIMEOUT_SECONDS=1,
    HUBSPOT_CONVERSATIONS_READ_TIMEOUT_SECONDS=2,
)
def test_conversations_get_and_public_resource_methods() -> None:
    client = HubSpotClient("token")
    with patch("requests.get", return_value=_response(200, {"id": "thread-1"})) as request:
        assert client.get_conversation_thread("thread-1") == {"id": "thread-1"}
        assert request.call_args.kwargs["params"] == {"association": "TICKET"}
    with patch("requests.get", return_value=_response(200, {"id": "message-1"})):
        assert client.get_conversation_message("thread-1", "message-1")["id"] == "message-1"
    page = {"results": [{"id": "m1"}, "bad"], "paging": {"next": {"after": "cursor"}}}
    with patch("requests.get", return_value=_response(200, page)):
        results, after = client.list_conversation_messages_page("thread-1", limit=1000)
    assert results == [{"id": "m1"}]
    assert after == "cursor"


@override_settings(
    HUBSPOT_CONVERSATIONS_MAX_ATTEMPTS=1,
    HUBSPOT_CONVERSATIONS_CONNECT_TIMEOUT_SECONDS=1,
    HUBSPOT_CONVERSATIONS_READ_TIMEOUT_SECONDS=2,
)
@pytest.mark.parametrize("status", [401, 403])
def test_conversations_auth_errors_are_terminal(status: int) -> None:
    with patch("requests.get", return_value=_response(status)), pytest.raises(HubSpotAPIError) as raised:
        HubSpotClient("token").get_conversation_thread("1")
    assert raised.value.retryable is False


@override_settings(
    HUBSPOT_CONVERSATIONS_MAX_ATTEMPTS=1,
    HUBSPOT_CONVERSATIONS_CONNECT_TIMEOUT_SECONDS=1,
    HUBSPOT_CONVERSATIONS_READ_TIMEOUT_SECONDS=2,
)
def test_conversations_not_found_and_malformed_json_are_typed() -> None:
    client = HubSpotClient("token")
    with patch("requests.get", return_value=_response(404)), pytest.raises(HubSpotResourceNotFoundError):
        client.get_conversation_thread("missing")
    with patch("requests.get", return_value=_response(200, ValueError("bad"))), pytest.raises(HubSpotAPIError):
        client.get_conversation_thread("bad-json")
    with patch("requests.get", return_value=_response(200, [])), pytest.raises(HubSpotAPIError):
        client.get_conversation_thread("bad-shape")


@override_settings(
    HUBSPOT_CONVERSATIONS_MAX_ATTEMPTS=2,
    HUBSPOT_CONVERSATIONS_CONNECT_TIMEOUT_SECONDS=1,
    HUBSPOT_CONVERSATIONS_READ_TIMEOUT_SECONDS=2,
)
def test_conversations_rate_limit_retries_then_succeeds() -> None:
    responses = [_response(429, headers={"Retry-After": "0"}), _response(200, {"id": "ok"})]
    with patch("requests.get", side_effect=responses), patch("time.sleep") as sleep:
        assert HubSpotClient("token").get_conversation_thread("1")["id"] == "ok"
    sleep.assert_called_once()
