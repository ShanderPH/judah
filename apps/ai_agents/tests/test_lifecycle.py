from types import SimpleNamespace

import pytest

from apps.ai_agents.models import ConversationEvent, ConversationInstance, ConversationStateTransition
from apps.ai_agents.services.lifecycle import (
    EventNormalizer,
    InvalidStateTransitionError,
    LifecycleEngine,
    NormalizedEvent,
    RoutingPolicyEngine,
)


def _event(**payload):
    return SimpleNamespace(
        event_type=payload.get("subscriptionType", "ticket.propertyChange"),
        object_id=str(payload.get("objectId", "")),
        payload=payload,
    )


def test_support_new_stage_routes_to_auto_assignment(settings) -> None:
    payload = {
        "subscriptionType": "ticket.propertyChange",
        "objectId": "ticket-1",
        "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}",
        "propertyValue": "1",
    }
    decision = RoutingPolicyEngine().route(EventNormalizer().normalize_webhook_event(_event(**payload)))

    assert decision.route == "AUTO_ASSIGNMENT"
    assert decision.target_state == ConversationInstance.State.QUEUE_PENDING


def test_support_closed_stage_routes_to_close(settings) -> None:
    payload = {
        "subscriptionType": "ticket.propertyChange",
        "objectId": "ticket-2",
        "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
        "propertyValue": "1",
    }
    decision = RoutingPolicyEngine().route(EventNormalizer().normalize_webhook_event(_event(**payload)))

    assert decision.route == "CLOSE"
    assert decision.target_state == ConversationInstance.State.CLOSED


def test_conversation_message_is_durable_but_has_no_bot_route() -> None:
    payload = {
        "subscriptionType": "conversation.newMessage",
        "objectId": "thread-1",
        "messageId": "message-1",
        "direction": "INCOMING",
    }
    normalized = EventNormalizer().normalize_webhook_event(_event(**payload))
    decision = RoutingPolicyEngine().route(normalized)

    assert normalized.hubspot_thread_id == "thread-1"
    assert decision.route == "IGNORE"


@pytest.mark.django_db
def test_lifecycle_records_ignored_conversation_without_agent_run() -> None:
    event = NormalizedEvent(
        source="hubspot",
        source_event_id="event-1",
        event_type="conversation_message_received",
        idempotency_key="hubspot:event-1",
        payload={},
        hubspot_thread_id="thread-1",
        direction="INCOMING",
        message_id="message-1",
    )

    result = LifecycleEngine().record_normalized_event(event)

    assert result.decision.route == "IGNORE"
    assert result.instance.state == ConversationInstance.State.IGNORED
    assert ConversationEvent.objects.filter(instance=result.instance).count() == 1


@pytest.mark.django_db
def test_lifecycle_rejects_invalid_transition() -> None:
    instance = ConversationInstance.objects.create(idempotency_key="invalid-transition")

    with pytest.raises(InvalidStateTransitionError):
        LifecycleEngine().transition(
            instance,
            ConversationInstance.State.AI_SERVICE_RUNNING,
            reason="invalid",
        )


def test_legacy_states_are_not_exposed() -> None:
    values = {value for value, _label in ConversationInstance.State.choices}
    assert values.isdisjoint(
        {"CONTACT_REQUIRED", "CONTACT_COLLECTING", "CONTACT_ASSOCIATING", "TRIAGE_PENDING", "TRIAGE_RUNNING"}
    )
    assert ConversationStateTransition._meta.get_field("to_state").choices == ConversationInstance.State.choices
