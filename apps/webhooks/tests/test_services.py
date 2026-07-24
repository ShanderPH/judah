"""Tests for the webhooks persistence / dispatch layer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_agents.models import ConversationEvent, ConversationInstance
from apps.webhooks.models import DeadLetterQueue, WebhookEvent
from apps.webhooks.services import _dispatch_hubspot_lifecycle, process_webhook_event, record_webhook_event


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

    def test_provider_event_id_is_idempotent_per_source_and_type(self) -> None:
        payload = {"eventId": "evt-deduplicated", "objectId": "42"}

        first = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload=payload,
        )
        duplicate = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload=payload,
        )

        assert duplicate.pk == first.pk
        assert WebhookEvent.objects.filter(deduplication_key=first.deduplication_key).count() == 1

    def test_reused_provider_event_id_does_not_collapse_distinct_events(self) -> None:
        first = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={"eventId": "evt-reused", "objectId": "42", "propertyValue": "first"},
        )
        second = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={"eventId": "evt-reused", "objectId": "43", "propertyValue": "second"},
        )

        assert second.pk != first.pk
        assert second.deduplication_key != first.deduplication_key

    def test_exact_redelivery_without_provider_event_id_is_idempotent(self) -> None:
        payload = {"objectId": "42", "propertyName": "subject", "propertyValue": "Help"}

        first = record_webhook_event(source="hubspot", event_type="ticket.propertyChange", payload=payload)
        duplicate = record_webhook_event(source="hubspot", event_type="ticket.propertyChange", payload=payload)

        assert duplicate.pk == first.pk

    def test_hubspot_retry_attempt_number_is_not_part_of_event_identity(self) -> None:
        first = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={"eventId": "evt-retry", "objectId": "42", "attemptNumber": 0},
        )
        retry = record_webhook_event(
            source="hubspot",
            event_type="ticket.propertyChange",
            payload={"eventId": "evt-retry", "objectId": "42", "attemptNumber": 2},
        )

        assert retry.pk == first.pk

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

    def test_processed_event_is_an_idempotent_success(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="unknown",
            payload={},
            processed=True,
        )

        assert process_webhook_event(event.pk) is True

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

    def test_missing_lifecycle_schema_does_not_block_hubspot_handler(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="ticket.propertyChange",
            payload={
                "objectId": "ticket-no-schema",
                "propertyName": "hs_v2_date_entered_939275049",
                "propertyValue": "1783022765000",
            },
        )
        with (
            patch("apps.ai_agents.services.lifecycle.is_lifecycle_schema_ready", return_value=False),
            patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event") as mock_handler,
            patch("apps.ai_agents.services.lifecycle.record_lifecycle_for_webhook_event") as mock_lifecycle,
        ):
            ok = process_webhook_event(event.pk)

        assert ok is True
        mock_lifecycle.assert_not_called()
        mock_handler.assert_called_once()
        event.refresh_from_db()
        assert event.processed is True

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

    def test_lifecycle_error_does_not_block_ticket_auto_assignment(self) -> None:
        ConversationInstance.objects.create(
            idempotency_key="conversation:ticket:ticket-blocked",
            hubspot_ticket_id="ticket-blocked",
            state=ConversationInstance.State.HUMAN_ASSIGNED,
        )
        event = WebhookEvent.objects.create(
            event_type="ticket.propertyChange",
            object_id="ticket-blocked",
            payload={
                "eventId": "evt-ticket-blocked",
                "objectId": "ticket-blocked",
                "propertyName": "hs_v2_date_entered_939275049",
                "propertyValue": "1783022765000",
            },
        )

        with (
            patch("apps.support.tasks.task_matchmaker_assign_single.delay") as mock_assign,
            patch(
                "apps.webhooks.handlers.hubspot_handler.transaction.on_commit", side_effect=lambda callback: callback()
            ),
        ):
            ok = process_webhook_event(event.pk)

        assert ok is True
        mock_assign.assert_called_once_with("ticket-blocked", "1783022765000", str(event.pk))
        event.refresh_from_db()
        assert event.processed is True
        assert event.retry_count == 0

    @patch("apps.ai_agents.tasks.schedule_salomao_thread_customer_turn")
    def test_lifecycle_ai_route_controls_dispatch(self, mock_pipeline) -> None:
        event = WebhookEvent.objects.create(
            event_type="conversation.newMessage",
            object_id="thread-authoritative",
            payload={
                "eventId": "evt-authoritative",
                "objectId": "thread-authoritative",
                "threadId": "thread-authoritative",
                "messageId": "message-authoritative",
                "direction": "INCOMING",
                "channel": "chat",
            },
        )

        with patch("django.conf.settings.AI_ROUTING_ENABLED", True):
            assert process_webhook_event(event.pk) is True

        mock_pipeline.assert_called_once_with("thread-authoritative")

    def test_failed_lifecycle_dispatch_is_retried_without_losing_ledger_status(self) -> None:
        event = WebhookEvent.objects.create(
            event_type="conversation.newMessage",
            object_id="thread-retry",
            payload={
                "eventId": "evt-retry",
                "objectId": "thread-retry",
                "threadId": "thread-retry",
                "messageId": "message-retry",
                "direction": "INCOMING",
                "channel": "chat",
            },
        )

        with patch(
            "apps.webhooks.services._dispatch_hubspot_lifecycle",
            side_effect=[RuntimeError("broker unavailable"), None],
        ) as dispatch:
            assert process_webhook_event(event.pk) is False
            lifecycle_event = ConversationEvent.objects.get()
            assert lifecycle_event.processing_status == lifecycle_event.ProcessingStatus.FAILED

            assert process_webhook_event(event.pk) is True

        assert dispatch.call_count == 2
        lifecycle_event.refresh_from_db()
        event.refresh_from_db()
        assert lifecycle_event.processing_status == lifecycle_event.ProcessingStatus.PROCESSED
        assert event.processed is True


@pytest.mark.django_db
class TestLifecycleDispatch:
    @staticmethod
    def _lifecycle(route: str, *, thread_id: str | None = None, ticket_id: str | None = None):
        return SimpleNamespace(
            decision=SimpleNamespace(route=route, reason="policy"),
            instance=SimpleNamespace(
                hubspot_thread_id=thread_id,
                hubspot_ticket_id=ticket_id,
            ),
        )

    @patch("apps.ai_agents.tasks.request_human_handoff_task.delay")
    def test_human_handoff_uses_dedicated_task(self, handoff) -> None:
        event = WebhookEvent(event_type="conversation.newMessage", payload={})

        _dispatch_hubspot_lifecycle(
            event,
            self._lifecycle("HUMAN_HANDOFF", thread_id="thread-human"),
        )

        handoff.assert_called_once_with(
            thread_id="thread-human",
            ticket_id=None,
            reason="policy",
        )

    @patch("apps.ai_agents.tasks.request_human_handoff_task.delay")
    def test_disabled_ai_falls_back_to_human(self, handoff) -> None:
        event = WebhookEvent(event_type="ticket.propertyChange", payload={})

        with patch("django.conf.settings.AI_ROUTING_ENABLED", False):
            _dispatch_hubspot_lifecycle(
                event,
                self._lifecycle("AI_TRIAGE", ticket_id="ticket-disabled"),
            )

        assert "AI routing is disabled" in handoff.call_args.kwargs["reason"]

    @patch("apps.ai_agents.tasks.schedule_supervisor_customer_turn")
    def test_ticket_customer_message_uses_debounced_supervisor(self, schedule) -> None:
        event = WebhookEvent(
            event_type="ticket.propertyChange",
            property_name="hs_last_message_from_visitor",
            property_value="true",
            payload={},
        )

        with patch("django.conf.settings.AI_ROUTING_ENABLED", True):
            _dispatch_hubspot_lifecycle(
                event,
                self._lifecycle("AI_TRIAGE", ticket_id="ticket-customer"),
            )

        schedule.assert_called_once_with(
            "ticket-customer",
            is_off_hours=False,
            enforce_ai_pipeline=True,
        )

    @patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay")
    def test_non_message_thread_event_runs_thread_pipeline(self, run_thread) -> None:
        event = WebhookEvent(event_type="conversation.threadUpdated", payload={})

        with patch("django.conf.settings.AI_ROUTING_ENABLED", True):
            _dispatch_hubspot_lifecycle(
                event,
                self._lifecycle("AI_TRIAGE", thread_id="thread-update"),
            )

        run_thread.assert_called_once_with("thread-update")

    @patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay")
    def test_non_message_ticket_event_runs_ticket_pipeline(self, run_ticket) -> None:
        event = WebhookEvent(event_type="ticket.propertyChange", payload={})

        with patch("django.conf.settings.AI_ROUTING_ENABLED", True):
            _dispatch_hubspot_lifecycle(
                event,
                self._lifecycle("AI_TRIAGE", ticket_id="ticket-update"),
            )

        run_ticket.assert_called_once_with("ticket-update", False)

    def test_ai_route_without_identifiers_fails_explicitly(self) -> None:
        event = WebhookEvent(event_type="ticket.propertyChange", payload={})

        with (
            patch("django.conf.settings.AI_ROUTING_ENABLED", True),
            pytest.raises(ValueError, match="no thread or ticket"),
        ):
            _dispatch_hubspot_lifecycle(event, self._lifecycle("AI_TRIAGE"))


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
        assert ConversationInstance.objects.count() == 1
        assert ConversationInstance.objects.get().state == ConversationInstance.State.IGNORED

    def test_process_contact_event_without_conversation_context_records_ignored_lifecycle(self) -> None:
        event = WebhookEvent.objects.create(event_type="contact.creation", payload={"objectId": "contact-1"})
        with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event"):
            process_webhook_event(event.pk)
        event.refresh_from_db()
        assert event.processed is True
        assert ConversationInstance.objects.count() == 1
        assert ConversationInstance.objects.get().state == ConversationInstance.State.IGNORED

    def test_dead_letter_str(self) -> None:
        event = WebhookEvent.objects.create(event_type="unknown", object_id="9", payload={})
        dlq = DeadLetterQueue.objects.create(event=event, failure_reason="timeout")
        assert "DLQ" in str(dlq)
