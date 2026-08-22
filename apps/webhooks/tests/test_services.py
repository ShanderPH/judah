from unittest.mock import patch

import pytest

from apps.webhooks.models import DeadLetterQueue, WebhookEvent
from apps.webhooks.services import process_webhook_event, record_webhook_event


@pytest.mark.django_db
def test_record_webhook_event_is_idempotent() -> None:
    payload = {"eventId": "event-1", "objectId": "ticket-1", "propertyName": "hubspot_owner_id"}

    first = record_webhook_event("hubspot", "ticket.propertyChange", payload)
    second = record_webhook_event("hubspot", "ticket.propertyChange", payload)

    assert first.pk == second.pk
    assert WebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_support_event_uses_deterministic_handler_when_lifecycle_is_unavailable() -> None:
    event = record_webhook_event(
        "hubspot",
        "ticket.propertyChange",
        {"eventId": "event-2", "objectId": "ticket-2", "propertyName": "hubspot_owner_id"},
    )

    with (
        patch("apps.ai_agents.services.lifecycle.is_lifecycle_schema_ready", return_value=False),
        patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event") as handler,
    ):
        assert process_webhook_event(event.pk) is True

    handler.assert_called_once_with(event)


@pytest.mark.django_db
def test_conversation_message_is_recorded_without_legacy_task_dispatch() -> None:
    event = record_webhook_event(
        "hubspot",
        "conversation.newMessage",
        {
            "eventId": "event-3",
            "objectId": "thread-3",
            "messageId": "message-3",
            "direction": "INCOMING",
        },
    )

    assert process_webhook_event(event.pk) is True
    event.refresh_from_db()
    assert event.processed is True


@pytest.mark.django_db
def test_handler_failure_retries_and_dead_letters_after_limit() -> None:
    event = record_webhook_event(
        "hubspot",
        "ticket.propertyChange",
        {"eventId": "event-4", "objectId": "ticket-4", "propertyName": "hubspot_owner_id"},
    )
    event.retry_count = 2
    event.save(update_fields=["retry_count"])

    with (
        patch("apps.ai_agents.services.lifecycle.is_lifecycle_schema_ready", return_value=False),
        patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event", side_effect=RuntimeError("boom")),
    ):
        assert process_webhook_event(event.pk) is False

    event.refresh_from_db()
    assert event.retry_count == 3
    assert DeadLetterQueue.objects.filter(event=event).exists()
