"""Tests for the deterministic conversation lifecycle engine."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.ai_agents.models import ConversationEvent, ConversationInstance, ConversationStateTransition
from apps.ai_agents.services.lifecycle import (
    EventNormalizer,
    InvalidStateTransitionError,
    LifecycleEngine,
    RoutingPolicyEngine,
    record_lifecycle_for_webhook_event,
)
from apps.webhooks.models import WebhookEvent
from apps.webhooks.services import process_webhook_event


def _conversation_event(**payload_overrides):
    payload = {
        "eventId": "evt-1",
        "subscriptionType": "conversation.newMessage",
        "objectId": "thread-123",
        "messageId": "msg-1",
        "direction": "INCOMING",
        "channel": "chat",
        "occurredAt": "1783022765000",
    }
    payload.update(payload_overrides)
    return SimpleNamespace(
        event_type="conversation.newMessage", payload=payload, object_id=payload["objectId"], id="db-1"
    )


@pytest.mark.django_db
def test_normalizer_extracts_conversation_message_identifiers() -> None:
    normalized = EventNormalizer().normalize_webhook_event(_conversation_event())

    assert normalized.event_type == "conversation_message_received"
    assert normalized.hubspot_thread_id == "thread-123"
    assert normalized.message_id == "msg-1"
    assert normalized.direction == "INCOMING"
    assert normalized.channel == "chat"
    assert normalized.idempotency_key == "hubspot:conversation.newMessage:evt-1"


@pytest.mark.django_db
def test_lifecycle_records_and_deduplicates_conversation_events() -> None:
    event = _conversation_event()

    first = record_lifecycle_for_webhook_event(event)
    second = record_lifecycle_for_webhook_event(event)

    assert first.event_created is True
    assert second.event_created is False
    assert first.instance.pk == second.instance.pk
    assert ConversationInstance.objects.count() == 1
    assert ConversationEvent.objects.count() == 1
    assert ConversationEvent.objects.get().processing_status == ConversationEvent.ProcessingStatus.DUPLICATE
    first.instance.refresh_from_db()
    assert first.instance.state == ConversationInstance.State.CONTEXT_HYDRATING


@pytest.mark.django_db
def test_lifecycle_deduplicates_events_without_provider_event_id() -> None:
    first_event = _conversation_event(eventId="")
    second_event = _conversation_event(eventId="")
    second_event.id = "db-2"

    first = record_lifecycle_for_webhook_event(first_event)
    second = record_lifecycle_for_webhook_event(second_event)

    assert first.event_created is True
    assert second.event_created is False
    assert ConversationInstance.objects.count() == 1
    assert ConversationEvent.objects.count() == 1


@pytest.mark.django_db
@override_settings(HUBSPOT_AI_REPLY_DISABLED_CHANNELS="whatsapp")
def test_routing_sends_unsupported_channel_to_handoff() -> None:
    normalized = EventNormalizer().normalize_webhook_event(_conversation_event(channel="whatsapp"))
    decision = RoutingPolicyEngine().route(normalized)

    assert decision.route == "HUMAN_HANDOFF"
    assert decision.target_state == ConversationInstance.State.HUMAN_HANDOFF_REQUESTED
    assert decision.can_send_reply is False


@pytest.mark.django_db
def test_lifecycle_rejects_invalid_transition() -> None:
    instance = ConversationInstance.objects.create(idempotency_key="conversation:test")

    with pytest.raises(InvalidStateTransitionError):
        LifecycleEngine().transition(
            instance,
            ConversationInstance.State.AI_SERVICE_RUNNING,
            reason="Invalid jump.",
        )

    assert ConversationStateTransition.objects.count() == 0


@pytest.mark.django_db
def test_process_webhook_event_records_lifecycle_before_hubspot_handler() -> None:
    event = WebhookEvent.objects.create(
        event_type="ticket.propertyChange",
        object_id="ticket-1",
        payload={
            "eventId": "evt-ticket-1",
            "objectId": "ticket-1",
            "propertyName": "hs_v2_date_entered_939275049",
            "propertyValue": "1783022765000",
        },
    )

    with patch("apps.webhooks.handlers.hubspot_handler.handle_hubspot_event") as mock_handler:
        ok = process_webhook_event(event.pk)

    assert ok is True
    mock_handler.assert_called_once()
    instance = ConversationInstance.objects.get(hubspot_ticket_id="ticket-1")
    assert instance.state == ConversationInstance.State.QUEUE_PENDING
    assert instance.events.count() == 1
    assert instance.state_transitions.count() == 2
