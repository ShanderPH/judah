"""Close occurrences stay dispatchable without terminalizing a later attendance."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_agents.models import ConversationEvent, ConversationInstance
from apps.ai_agents.services.lifecycle import (
    EffectOrderingPolicy,
    EventNormalizer,
    LifecycleEngine,
    RoutingPolicyEngine,
)
from apps.support.auto_assign_service import handle_ticket_closed
from apps.support.models import AssignedConversation, ClosedConversation
from apps.support.tests.test_ticket_close_service import T0, T1, assignment, cycle, snapshot
from apps.webhooks.services import process_webhook_event, record_webhook_event


def event(property_name, value, occurred_at):
    """Build a ticket property-change event with provider occurrence time."""
    payload = {
        "objectId": "close-ticket",
        "subscriptionType": "ticket.propertyChange",
        "propertyName": property_name,
        "propertyValue": value,
        "occurredAt": occurred_at,
        "eventId": f"{property_name}:{occurred_at}",
    }
    return SimpleNamespace(event_type="ticket.propertyChange", object_id="close-ticket", payload=payload)


def test_close_without_provider_id_uses_delivery_id(settings):
    """Match close ledger identity to task identity when provider ID is absent."""
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", "1790000000000", 1790000000000)
    raw.payload.pop("eventId")
    raw.pk = "delivery-id"
    raw.event_id = ""
    normalized = EventNormalizer().normalize_webhook_event(raw)
    assert normalized.source_event_id == "delivery-id"


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
    """Only calculated stage entries use idempotent occurrence routing."""
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
    """A later owner update cannot suppress a proven close occurrence."""
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
    """Current closure reaches every lifecycle instance for the ticket."""
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


def test_confirmed_first_close_records_cursor_and_rejects_older_event(settings):
    """A confirmed first close establishes the provider cursor."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = "off"
    target = cycle()
    assignment(target)
    closed_ms = int(T1.timestamp() * 1000)
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", str(closed_ms), closed_ms)
    engine = LifecycleEngine()
    recorded = engine.record_normalized_event(EventNormalizer().normalize_webhook_event(raw))
    assert "last_provider_event_occurred_at" not in recorded.instance.metadata
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        handle_ticket_closed("close-ticket", str(closed_ms), source_event_id=raw.payload["eventId"])
    recorded.instance.refresh_from_db()
    assert recorded.instance.metadata["last_provider_event_occurred_at"] == T1.isoformat()
    older = event("hubspot_owner_id", "700", int(T0.timestamp() * 1000))
    assert engine.record_normalized_event(EventNormalizer().normalize_webhook_event(older)).stale_event
    recorded.instance.refresh_from_db()
    assert recorded.instance.metadata["last_payload"] == raw.payload


@pytest.mark.parametrize("source_event_id,persist_null_event", [("close-id", False), ("close-id", True), ("", False)])
def test_close_without_timestamped_ledger_event_rejects_older_reopen(settings, source_event_id, persist_null_event):
    """A proven close without a timestamped ledger event blocks older deliveries."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    instance = ConversationInstance.objects.create(
        hubspot_ticket_id="close-ticket", idempotency_key="close-without-event", state="HUMAN_ASSIGNED"
    )
    if persist_null_event:
        ConversationEvent.objects.create(
            instance=instance,
            source="hubspot",
            source_event_id="close-id",
            event_type="ticket_closed",
            occurred_at=None,
            idempotency_key="close-event-without-timestamp",
        )
    engine = LifecycleEngine()
    assert engine.close_ticket_instances(
        "close-ticket", reason="Proven closure.", source_event_id=source_event_id, occurred_at=T1
    )
    instance.refresh_from_db()
    assert instance.metadata["last_provider_event_occurred_at"] == T1.isoformat()

    older = event(
        f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}",
        str(int(T0.timestamp() * 1000)),
        int(T0.timestamp() * 1000),
    )
    result = engine.record_normalized_event(EventNormalizer().normalize_webhook_event(older))
    instance.refresh_from_db()
    assert result.stale_event
    assert instance.state == "CLOSED"
    assert instance.closed_at == T1


def test_explicit_close_time_overrides_ledger_time_and_rejects_older_reopen(settings):
    """An N1 entry between the ledger time and proven closure cannot reopen."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    instance = ConversationInstance.objects.create(
        hubspot_ticket_id="close-ticket", idempotency_key="close-distinct-times", state="HUMAN_ASSIGNED"
    )
    ConversationEvent.objects.create(
        instance=instance,
        source="hubspot",
        source_event_id="close-id",
        event_type="ticket_closed",
        occurred_at=T0,
        idempotency_key="close-event-earlier-ledger-time",
    )
    engine = LifecycleEngine()
    assert engine.close_ticket_instances(
        "close-ticket", reason="Proven closure.", source_event_id="close-id", occurred_at=T1
    )

    n1_at = T0 + (T1 - T0) / 2
    n1_ms = int(n1_at.timestamp() * 1000)
    older = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_NEW_STAGE_ID}", str(n1_ms), n1_ms)
    result = engine.record_normalized_event(EventNormalizer().normalize_webhook_event(older))

    instance.refresh_from_db()
    assert result.stale_event
    assert instance.metadata["last_provider_event_occurred_at"] == T1.isoformat()
    assert instance.state == "CLOSED"
    assert instance.closed_at == T1
    assert instance.service_cycles.count() == 1


def test_confirmed_stale_close_preserves_newer_cursor_and_snapshot(settings):
    """A stale close cannot rewind cursor or operational payload."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = "off"
    target = cycle()
    assignment(target)
    engine = LifecycleEngine()
    newer_at = T1 + timedelta(hours=1)
    newer = event("hubspot_owner_id", "700", int(newer_at.timestamp() * 1000))
    instance = engine.record_normalized_event(EventNormalizer().normalize_webhook_event(newer)).instance
    closed_ms = int(T1.timestamp() * 1000)
    raw = event(f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}", str(closed_ms), closed_ms)
    assert engine.record_normalized_event(EventNormalizer().normalize_webhook_event(raw)).stale_event
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        handle_ticket_closed("close-ticket", str(closed_ms), source_event_id=raw.payload["eventId"])
    instance.refresh_from_db()
    assert instance.metadata["last_provider_event_occurred_at"] == newer_at.isoformat()
    assert instance.metadata["last_payload"] == newer.payload


def test_calculated_close_does_not_close_lifecycle_before_cycle_resolution(settings):
    """Calculated close waits for service-cycle resolution."""
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
    """Generic stage observations do not close enforced lifecycle state."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")
    raw = event("hs_pipeline_stage", settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID, 1790000000000)
    result = LifecycleEngine().record_normalized_event(EventNormalizer().normalize_webhook_event(raw))
    instance.refresh_from_db()
    assert result.effect_policy == EffectOrderingPolicy.REVALIDATE_CURRENT_PROVIDER_STATE
    assert instance.state == "HUMAN_ASSIGNED"
    assert instance.closed_at is None


def test_stale_close_dispatch_retries_after_broker_failure(settings):
    """A failed broker dispatch keeps stale close occurrence retryable."""
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
