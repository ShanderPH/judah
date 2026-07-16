"""Direct coverage for canonical webhook API policy branches."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory, override_settings
from ninja.errors import HttpError

from apps.webhooks import api


def test_signature_wrapper_helpers() -> None:
    request = Mock()
    with (
        patch("apps.webhooks.api.verify_hubspot_signature_v1", return_value=True),
        patch("apps.webhooks.api.verify_hubspot_signature_v3", return_value=True),
        patch("apps.webhooks.api.is_valid_hubspot_request", return_value=True),
    ):
        assert api._verify_hubspot_signature_v1(request, "secret") is True
        assert api._verify_hubspot_signature_v3(request, "secret") is True
        assert api._is_valid_hubspot_request(request, "secret") is True

    request.headers = {"x-hub-signature": "invalid"}
    assert api._verify_jira_signature(request, "secret") is False


@override_settings(HUBSPOT_APP_SECRET="", DEBUG=False)
def test_hubspot_webhook_fails_closed_without_secret() -> None:
    request = RequestFactory().post("/webhook", data=b"[]", content_type="application/json")
    with pytest.raises(HttpError):
        api.hubspot_webhook(request, [])


@override_settings(HUBSPOT_APP_SECRET="", DEBUG=True)
def test_hubspot_webhook_debug_accepts_and_queues() -> None:
    request = RequestFactory().post("/webhook", data=b"[]", content_type="application/json")
    event = SimpleNamespace(pk="event-1")
    with (
        patch("apps.webhooks.api.record_webhook_event", return_value=event) as record,
        patch("apps.webhooks.tasks.process_webhook_event_task.delay") as delay,
    ):
        status, result = api.hubspot_webhook(
            request,
            [{"subscriptionType": "ticket.creation", "objectId": "1"}],
        )
    assert status == 202
    assert result["events_queued"] == 1
    record.assert_called_once()
    delay.assert_called_once_with("event-1")


@override_settings(HUBSPOT_APP_SECRET="secret", DEBUG=False)
def test_hubspot_webhook_bad_signature_persists_without_dispatch() -> None:
    request = RequestFactory().post("/webhook", data=b"[]", content_type="application/json")
    with (
        patch("apps.webhooks.api._is_valid_hubspot_request", return_value=False),
        patch("apps.webhooks.api.record_webhook_event", return_value=SimpleNamespace(pk="event-1")),
        patch("apps.webhooks.tasks.process_webhook_event_task.delay") as delay,
    ):
        status, result = api.hubspot_webhook(request, [{"objectId": "1"}])
    assert status == 202
    assert result["status"] == "signature_mismatch"
    assert result["events_queued"] == 0
    delay.assert_not_called()


@override_settings(JIRA_WEBHOOK_SECRET="", DEBUG=True)
def test_jira_webhook_debug_accepts_without_secret() -> None:
    request = RequestFactory().post("/webhook", data=b"{}", content_type="application/json")
    with (
        patch("apps.webhooks.api.record_webhook_event", return_value=SimpleNamespace(pk="event-1")),
        patch("apps.webhooks.tasks.process_webhook_event_task.delay") as delay,
    ):
        status, result = api.jira_webhook(request, {"webhookEvent": "unknown"})
    assert status == 202
    assert result["event_id"] == "event-1"
    delay.assert_called_once_with("event-1")
