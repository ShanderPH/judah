"""Tests for the deterministic conversation lifecycle engine."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.ai_agents.models import ConversationEvent, ConversationInstance, ConversationStateTransition
from apps.ai_agents.services.lifecycle import (
    EventNormalizer,
    InvalidStateTransitionError,
    LifecycleEngine,
    NormalizedEvent,
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
def test_lifecycle_uses_message_id_when_provider_event_id_is_missing() -> None:
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
def test_outgoing_event_is_logged_without_terminalizing_active_conversation() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:outgoing-preserves-state",
        hubspot_thread_id="outgoing-preserves-state",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
    )
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="evt-outgoing",
        event_type="conversation_message_received",
        idempotency_key="hubspot:conversation.newMessage:evt-outgoing",
        payload={"direction": "OUTGOING"},
        hubspot_thread_id="outgoing-preserves-state",
        channel="chat",
        direction="OUTGOING",
        message_id="outgoing-message",
    )

    result = LifecycleEngine().record_normalized_event(event)

    instance.refresh_from_db()
    assert result.event_created is True
    assert result.decision.route == "IGNORE"
    assert instance.state == ConversationInstance.State.WAITING_FOR_CUSTOMER


@pytest.mark.django_db
def test_outgoing_event_starts_assigned_human_work() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:human-started",
        hubspot_thread_id="human-started",
        state=ConversationInstance.State.HUMAN_ASSIGNED,
    )
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="evt-human-outgoing",
        event_type="conversation_message_received",
        idempotency_key="hubspot:conversation.newMessage:evt-human-outgoing",
        payload={"direction": "OUTGOING"},
        hubspot_thread_id="human-started",
        channel="chat",
        direction="OUTGOING",
        message_id="human-outgoing-message",
    )

    LifecycleEngine().record_normalized_event(event)

    instance.refresh_from_db()
    assert instance.state == ConversationInstance.State.HUMAN_IN_PROGRESS


@pytest.mark.django_db
@override_settings(HUBSPOT_AI_REPLY_DISABLED_CHANNELS="email")
def test_routing_sends_unsupported_channel_to_handoff() -> None:
    normalized = EventNormalizer().normalize_webhook_event(_conversation_event(channel="email"))
    decision = RoutingPolicyEngine().route(normalized)

    assert decision.route == "HUMAN_HANDOFF"
    assert decision.target_state == ConversationInstance.State.HUMAN_HANDOFF_REQUESTED
    assert decision.can_send_reply is False


@pytest.mark.django_db
@override_settings(HUBSPOT_AI_REPLY_DISABLED_CHANNELS="whatsapp")
def test_routing_never_blocks_whatsapp_from_legacy_environment_value() -> None:
    normalized = EventNormalizer().normalize_webhook_event(_conversation_event(channel="whatsapp"))
    decision = RoutingPolicyEngine().route(normalized)

    assert decision.route != "HUMAN_HANDOFF"
    assert decision.can_send_reply is True


@pytest.mark.django_db
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="triage-pipeline",
    HUBSPOT_N1_NEW_STAGE_ID="new-service",
    HUBSPOT_AI_TRIAGE_STAGE_ID="showing-menu",
    HUBSPOT_CLOSED_STAGE_ID="service-closed",
)
@pytest.mark.parametrize("stage_id", ["new-service", "showing-menu"])
def test_routing_uses_configured_ai_triage_pipeline_stages(stage_id: str) -> None:
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="event-1",
        event_type="ticket_stage_changed",
        idempotency_key="event-1",
        payload={},
        pipeline_id="triage-pipeline",
        pipeline_stage_id=stage_id,
    )

    decision = RoutingPolicyEngine().route(event)

    assert decision.route == "AI_TRIAGE"
    assert decision.target_state == ConversationInstance.State.CONTEXT_HYDRATING


@pytest.mark.django_db
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="triage-pipeline",
    HUBSPOT_CLOSED_STAGE_ID="service-closed",
)
def test_routing_closes_configured_ai_triage_pipeline_stage() -> None:
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="event-1",
        event_type="ticket_stage_changed",
        idempotency_key="event-1",
        payload={},
        pipeline_id="triage-pipeline",
        pipeline_stage_id="service-closed",
    )

    decision = RoutingPolicyEngine().route(event)

    assert decision.route == "CLOSE"
    assert decision.target_state == ConversationInstance.State.CLOSED


@pytest.mark.django_db
@override_settings(
    HUBSPOT_AI_TRIAGE_PIPELINE_ID="triage-pipeline",
    HUBSPOT_AI_TRIAGE_STAGE_ID="showing-menu",
)
def test_routing_does_not_apply_ai_stage_to_another_pipeline() -> None:
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="event-1",
        event_type="ticket_stage_changed",
        idempotency_key="event-1",
        payload={},
        pipeline_id="another-pipeline",
        pipeline_stage_id="showing-menu",
    )

    decision = RoutingPolicyEngine().route(event)

    assert decision.route == "IGNORE"


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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "terminal_state",
    [ConversationInstance.State.IGNORED, ConversationInstance.State.CLOSED],
)
def test_ticket_entered_n1_reopens_terminal_lifecycle(terminal_state: str) -> None:
    closed_at = timezone.now() if terminal_state == ConversationInstance.State.CLOSED else None
    instance = ConversationInstance.objects.create(
        idempotency_key=f"conversation:ticket:reopened-{terminal_state}",
        hubspot_ticket_id=f"reopened-{terminal_state}",
        state=terminal_state,
        closed_at=closed_at,
    )
    event = SimpleNamespace(
        event_type="ticket.propertyChange",
        payload={
            "eventId": f"evt-reopened-{terminal_state}",
            "objectId": instance.hubspot_ticket_id,
            "propertyName": "hs_v2_date_entered_939275049",
            "propertyValue": "1783022765000",
        },
        object_id=instance.hubspot_ticket_id,
        id=f"db-reopened-{terminal_state}",
    )

    result = record_lifecycle_for_webhook_event(event)

    result.instance.refresh_from_db()
    assert result.instance.state == ConversationInstance.State.QUEUE_PENDING
    assert result.instance.closed_at is None
    assert ConversationStateTransition.objects.filter(
        instance=instance,
        from_state=terminal_state,
        to_state=ConversationInstance.State.QUEUE_PENDING,
    ).exists()
