"""Typed outcome coverage for assignment-time HubSpot user lookups."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from apps.integrations.hubspot.client import HubSpotClient
from apps.integrations.hubspot.exceptions import (
    HubSpotAPIError,
    HubSpotFailureKind,
    HubSpotResourceNotFoundError,
)


def _response(status: int, payload: dict | None = None, retry_after: str | None = None) -> Mock:
    response = Mock()
    response.status_code = status
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    response.json.return_value = payload or {}
    return response


def test_user_lookup_success() -> None:
    payload = {
        "id": "77",
        "properties": {
            "hs_email": "agent@example.test",
            "hs_availability_status": "available",
        },
    }
    with patch("requests.get", return_value=_response(200, payload)):
        result = HubSpotClient("secret").get_user_by_id("77")
    assert result["id"] == "77"
    assert result["hs_availability_status"] == "available"


def test_user_lookup_not_found_is_typed() -> None:
    with (
        patch("requests.get", return_value=_response(404)),
        pytest.raises(HubSpotResourceNotFoundError),
    ):
        HubSpotClient("secret").get_user_by_id("77")


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, HubSpotFailureKind.UNAUTHORIZED),
        (403, HubSpotFailureKind.FORBIDDEN),
    ],
)
def test_user_lookup_auth_failures_are_not_retryable(status: int, kind: str) -> None:
    with (
        patch("requests.get", return_value=_response(status)),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        HubSpotClient("secret").get_user_by_id("77")
    assert captured.value.error_code == kind
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, HubSpotFailureKind.RATE_LIMITED),
        (503, HubSpotFailureKind.SERVER_ERROR),
    ],
)
def test_user_lookup_retryable_statuses_are_bounded(status: int, kind: str) -> None:
    with (
        patch("requests.get", return_value=_response(status, retry_after="0")),
        patch("time.sleep"),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        HubSpotClient("secret").get_user_by_id("77")
    assert captured.value.error_code == kind
    assert captured.value.retryable is True


def test_user_lookup_timeout_is_typed() -> None:
    with (
        patch("requests.get", side_effect=requests.Timeout("timeout")),
        patch("time.sleep"),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        HubSpotClient("secret").get_user_by_id("77")
    assert captured.value.error_code == HubSpotFailureKind.TIMEOUT


def test_user_lookup_malformed_response_fails_closed() -> None:
    with (
        patch("requests.get", return_value=_response(200, {"id": "77"})),
        pytest.raises(HubSpotAPIError) as captured,
    ):
        HubSpotClient("secret").get_user_by_id("77")
    assert captured.value.error_code == HubSpotFailureKind.MALFORMED_RESPONSE
