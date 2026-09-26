"""Close occurrences stay dispatchable without terminalizing a later attendance."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.lifecycle import (
    EffectOrderingPolicy,
    EventNormalizer,
    LifecycleEngine,
    RoutingPolicyEngine,
)
from apps.support.auto_assign_service import handle_ticket_closed
from apps.support.models import AssignedConversation, ClosedConversation
from apps.support.tests.test_ticket_close_service import T1, assignment, cycle, snapshot
from apps.webhooks.services import process_webhook_event, record_webhook_event


def event(property_name, value, occurred_at):
    payload = {
        "objectId": "close-ticket",
        "subscriptionType": "ticket.propertyChange",
        "propertyName": property_name,
        "propertyValue": value,
        "occurredAt": occurred_at,
        "eventId": f"{property_name}:{occurred_at}",
    }
    return SimpleNamespace(event_type="ticket.propertyChange", object_id="close-ticket", payload=payload)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("new", EffectOrderingPolicy.PROCESS_IDEMPOTENT_OCCURRENCE),
        ("close", EffectOrderingPolicy.PROCESS_IDEMPOTENT_OCCURRENCE),
        ("generic", EffectOrderingPolicy.REVALIDATE_CURRENT_PROVIDER_STATE),
        ("owner", EffectOrderingPolicy.PRESERVE_PROJECTION_ONLY),
        ("ignored", EffectOrderingPolicy.PRESERVE_PROJECTION_ONLY),
    ],
)
def test_policy_only_admits_occurrences(settings, kind, expected):
    names = {
        "new": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}",
        "close": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
        "generic": "hs_pipeline_stage",
        "owner": "hubspot_owner_id",
        "ignored": "subject",
    }
    value = settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID if kind == "generic" else "1790000000000"
    normalized = EventNormalizer().normalize_webhook_event(event(names[kind], value, 1790000000000))
    assert LifecycleEngine.effect_ordering_policy(normalized, RoutingPolicyEngine().route(normalized)) == expected


def test_owner_removal_after_close_does_not_suppress_occurrence(settings):
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = "off"
    target = cycle()
    assignment(target)
    closed_ms = int(T1.timestamp() * 1000)
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")
    engine = LifecycleEngine()
    for delta in (5000, 10000):
        normalized = EventNormalizer().normalize_webhook_event(event("hubspot_owner_id", "", closed_ms + delta))
        engine.record_normalized_event(normalized)
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", str(closed_ms), closed_ms)
    webhook = record_webhook_event("hubspot", "ticket.propertyChange", raw.payload)
    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
        patch(
            "apps.support.tasks.task_handle_ticket_closed.delay",
            side_effect=lambda ticket_id, closed_at, owner_id, source_id: handle_ticket_closed(
                ticket_id, closed_at, owner_id, source_event_id=source_id
            ),
        ) as close,
    ):
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        assert process_webhook_event(webhook.pk)
    close.assert_called_once()
    target.refresh_from_db()
    instance.refresh_from_db()
    assert target.state == "closed"
    assert target.closed_at == T1
    assert not AssignedConversation.objects.filter(cycle=target).exists()
    assert ClosedConversation.objects.filter(cycle=target).count() == 1
    assert instance.state == "CLOSED"
    assert instance.closed_at == T1
    assert instance.service_cycles.filter(status="CLOSED").latest("sequence").closed_at == T1


def test_current_close_converges_every_ticket_instance(settings):
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = "off"
    target = cycle()
    assignment(target)
    instances = [
        ConversationInstance.objects.create(
            hubspot_ticket_id="close-ticket",
            hubspot_thread_id=f"thread-{index}",
            idempotency_key=f"close-instance-{index}",
            state=state,
        )
        for index, state in enumerate(("HUMAN_ASSIGNED", "WAITING_FOR_CUSTOMER"))
    ]
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        result = handle_ticket_closed("close-ticket", str(int(T1.timestamp() * 1000)))
    assert result.classification == "applied_current"
    for instance in instances:
        instance.refresh_from_db()
        assert instance.state == "CLOSED"
        assert instance.closed_at == T1
        assert instance.service_cycles.filter(status="CLOSED").latest("sequence").closed_at == T1


def test_calculated_close_does_not_close_lifecycle_before_cycle_resolution(settings):
    instance = ConversationInstance.objects.create(
        hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED", pipeline_stage_id="open-stage"
    )
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", "1790000000000", 1790000000000)
    result = LifecycleEngine().record_normalized_event(EventNormalizer().normalize_webhook_event(raw))
    instance.refresh_from_db()
    assert result.stale_event is False
    assert instance.state == "HUMAN_ASSIGNED"
    assert instance.pipeline_stage_id == "open-stage"


def test_generic_stage_observation_does_not_close_enforced_lifecycle(settings):
    settings.CONVERSATION_CYCLES_ENFORCED = True
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")
    raw = event("hs_pipeline_stage", settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID, 1790000000000)
    result = LifecycleEngine().record_normalized_event(EventNormalizer().normalize_webhook_event(raw))
    instance.refresh_from_db()
    assert result.effect_policy == EffectOrderingPolicy.REVALIDATE_CURRENT_PROVIDER_STATE
    assert instance.state == "HUMAN_ASSIGNED"
    assert instance.closed_at is None


def test_stale_close_dispatch_retries_after_broker_failure(settings):
    engine = LifecycleEngine()
    owner = EventNormalizer().normalize_webhook_event(event("hubspot_owner_id", "", 1790000010000))
    engine.record_normalized_event(owner)
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", "1790000000000", 1790000000000)
    webhook = record_webhook_event("hubspot", "ticket.propertyChange", raw.payload)
    with patch(
        "apps.support.tasks.task_handle_ticket_closed.delay", side_effect=[RuntimeError("broker"), None]
    ) as close:
        assert not process_webhook_event(webhook.pk)
        assert process_webhook_event(webhook.pk)
    assert close.call_count == 2
