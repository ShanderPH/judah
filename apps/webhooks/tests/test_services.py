"""Tests for the webhooks persistence / dispatch layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.ai_agents.models import ConversationInstance
from apps.webhooks.models import DeadLetterQueue, WebhookEvent
from apps.webhooks.services import process_webhook_event, record_webhook_event


@pytest.mark.django_db
class TestRecordWebhookEvent:
    def test_persists_event_with_payload(self) -> None:
        event = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={
                "eventId": "evt-1",
                "objectId": "42",
                "propertyName": "hs_pipeline_stage",
                "propertyValue": "939275052",
            },
        )
        assert event.pk is not None
        assert event.event_type == "ticket.propertyChange"
        assert event.object_id == "42"
        assert event.property_name == "hs_pipeline_stage"
        assert event.property_value == "939275052"
        assert event.processed is False

    def test_accepts_snake_case_aliases(self) -> None:
        event = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={
                "object_id": "99",
                "property_name": "foo",
                "property_value": "bar",
            },
        )
        assert event.object_id == "99"
        assert event.property_name == "foo"
        assert event.property_value == "bar"

    def test_missing_fields_default_to_empty(self) -> None:
        # DB CHECK constraint on event_type only admits an allowlist —
        # "unknown" is the canonical catch-all used by production code.
        event = record_webhook_event(
            source="hubspot",
            event_type="unknown",
            payload={},
        )
        assert event.event_id == ""
        assert event.object_id == ""
        assert event.property_name is None


@pytest.mark.django_db
class TestProcessWebhookEvent:
    def test_returns_false_when_event_missing(self) -> None:
        assert process_webhook_event("00000000-0000-0000-0000-000000000000") is False

    def test_routes_ticket_event_to_hubspot_handler(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="ticket.propertyChange",
            payload={"objectId": "1"},
        )
        with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event") as mock_handler:
            ok = process_webhook_event(event.pk)
        assert ok is True
        mock_handler.assert_called_once()
        event.refresh_from_db()
        assert event.processed is True
        assert event.processed_at is not None

    def test_routes_contact_event_to_hubspot_handler(self) -> None:
        event = WebhookEvent.objects.create(event_type="contact.creation", payload={})
        with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event") as mock_handler:
            process_webhook_event(event.pk)
        mock_handler.assert_called_once()

    def test_unknown_event_type_still_marked_processed(self) -> None:
        event = WebhookEvent.objects.create(event_type="unknown", payload={"x": 1})
        ok = process_webhook_event(event.pk)
        event.refresh_from_db()
        assert ok is True
        assert event.processed is True

    def test_handler_exception_increments_retry(self) -> None:
        event = WebhookEvent.objects.create(event_type="ticket.propertyChange", payload={})
        with patch(
            "apps.webhooks.handlers.hubspot_handler.handle_hubspot_event",
            side_effect=RuntimeError("boom"),
        ):
            ok = process_webhook_event(event.pk)
        assert ok is False
        event.refresh_from_db()
        assert event.retry_count == 1
        assert "boom" in event.error_message
        assert event.processed is False

    def test_third_failure_moves_to_dead_letter(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="ticket.propertyChange",
            payload={},
            retry_count=2,
        )
        with patch(
            "apps.webhooks.handlers.hubspot_handler.handle_hubspot_event",
            side_effect=RuntimeError("permanent"),
        ):
            process_webhook_event(event.pk)
        event.refresh_from_db()
        assert event.retry_count == 3
        assert DeadLetterQueue.objects.filter(event=event).exists()


@pytest.mark.django_db
class TestModelStringReprs:
    def test_webhook_event_str(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="ticket.creation",
            object_id="321",
            payload={},
        )
        rendered = str(event)
        assert "ticket.creation" in rendered
        assert "321" in rendered

    def test_process_routes_company_event(self) -> None:
        # Must use an allowlisted HubSpot event_type due to DB CHECK constraint.
        event = WebhookEvent.objects.create(event_type="company.creation", payload={})
        with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event"):
            process_webhook_event(event.pk)
        event.refresh_from_db()
        assert event.processed is True
        assert ConversationInstance.objects.count() == 0

    def test_process_contact_event_without_conversation_context_skips_lifecycle(self) -> None:
        event = WebhookEvent.objects.create(event_type="contact.creation", payload={"objectId": "contact-1"})
        with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event"):
            process_webhook_event(event.pk)
        event.refresh_from_db()
        assert event.processed is True
        assert ConversationInstance.objects.count() == 0

    def test_dead_letter_str(self) -> None:
        event = WebhookEvent.objects.create(event_type="unknown", object_id="9", payload={})
        dlq = DeadLetterQueue.objects.create(event=event, failure_reason="timeout")
        assert "DLQ" in str(dlq)
