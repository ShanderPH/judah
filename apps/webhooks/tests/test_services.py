from unittest.mock import patch

import pytest

from apps.webhooks.models import DeadLetterQueue, WebhookEvent
from apps.webhooks.services import process_webhook_event, record_webhook_event
from common.idempotency import canonical_event_key


@pytest.mark.django_db
def test_record_webhook_event_is_idempotent() -> None:
    payload = {"eventId": "event-1", "objectId": "ticket-1", "propertyName": "hubspot_owner_id"}

    first = record_webhook_event("hubspot", "ticket.propertyChange", payload)
    second = record_webhook_event("hubspot", "ticket.propertyChange", payload)

    assert first.pk == second.pk
    assert WebhookEvent.objects.count() == 1
    assert first.source == "hubspot"


@pytest.mark.django_db
@pytest.mark.parametrize("source", ["hubspot", "jira"])
def test_record_webhook_event_persists_source_for_each_writer(source: str) -> None:
    payload = {"eventId": f"event-{source}", "objectId": f"object-{source}"}

    event = record_webhook_event(source, "ticket.created", payload)

    assert event.source == source


@pytest.mark.django_db
def test_duplicate_with_legacy_empty_source_is_not_backfilled() -> None:
    payload = {"eventId": "legacy-event", "objectId": "legacy-object"}
    deduplication_key = canonical_event_key(source="hubspot", event_type="ticket.created", payload=payload)
    legacy = WebhookEvent.objects.create(
        source="",
        deduplication_key=deduplication_key,
        event_type="ticket.created",
        event_id="legacy-event",
        object_id="legacy-object",
        payload=payload,
    )

    duplicate = record_webhook_event("hubspot", "ticket.created", payload)

    assert duplicate.pk == legacy.pk
    duplicate.refresh_from_db()
    assert duplicate.source == ""


@pytest.mark.django_db
def test_new_empty_source_is_counted_without_payload_dimensions() -> None:
    payload = {"eventId": "empty-source", "email": "sensitive@example.test"}

    with patch("apps.webhooks.metrics.emit_metric") as emit:
        event = record_webhook_event("", "ticket.created", payload)

    assert event.source == ""
    emit.assert_called_once_with("webhook_events_empty_source_total")
    assert "sensitive" not in str(emit.call_args)


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
