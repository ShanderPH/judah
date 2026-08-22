"""Active-thread message reconciliation tests."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.ai_agents.models import ConversationInstance
from apps.webhooks.models import HubSpotReconciliationCursor, OutboxEvent, WebhookEvent
from apps.webhooks.n8n_inbound import canonical_hubspot_message_key
from apps.webhooks.reconciliation import hydrate_webhook_message_event, reconcile_active_threads


@pytest.mark.django_db
@override_settings(
    HUBSPOT_PORTAL_ID="47354717",
    N8N_BOT_RECONCILIATION_ENABLED=True,
    N8N_BOT_RECONCILIATION_BATCH_SIZE=10,
    N8N_BOT_RECONCILIATION_LOOKBACK_SECONDS=300,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
    N8N_BOT_MAX_DELIVERY_ATTEMPTS=8,
)
def test_reconciliation_paginates_and_advances_cursor_after_ingestion() -> None:
    instance = ConversationInstance.objects.create(
        hubspot_thread_id="thread-1",
        state=ConversationInstance.State.WAITING_FOR_CUSTOMER,
        idempotency_key="instance-thread-1",
    )
    client = Mock()
    client.get_conversation_thread.return_value = {
        "id": "thread-1",
        "status": "OPEN",
        "spam": False,
        "threadAssociations": {"associatedTicketId": "ticket-1"},
    }
    first = {
        "id": "message-1",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "one",
        "createdAt": "2026-08-22T15:00:00Z",
        "senders": [{"actorId": "V-1"}],
    }
    second = {**first, "id": "message-2", "text": "two"}
    client.list_conversation_messages_page.side_effect = [([first], "next"), ([second], None)]

    with (
        patch("apps.webhooks.reconciliation.get_hubspot_client", return_value=client),
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
    ):
        assert reconcile_active_threads() == 2

    cursor = HubSpotReconciliationCursor.objects.get(conversation_instance=instance)
    assert cursor.last_message_id == "message-2"
    assert cursor.last_reconciled_at is not None
    assert OutboxEvent.objects.count() == 2
    assert client.list_conversation_messages_page.call_count == 2


@pytest.mark.django_db
@override_settings(N8N_BOT_RECONCILIATION_ENABLED=True, N8N_BOT_RECONCILIATION_BATCH_SIZE=10)
def test_terminal_threads_are_not_selected() -> None:
    ConversationInstance.objects.create(
        hubspot_thread_id="thread-closed",
        state=ConversationInstance.State.CLOSED,
        idempotency_key="instance-closed",
    )
    with patch("apps.webhooks.reconciliation.get_hubspot_client") as client:
        assert reconcile_active_threads() == 0
    client.assert_not_called()


@pytest.mark.django_db
@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=8)
def test_webhook_hydration_uses_canonical_ingestion() -> None:
    event = WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id="provider-1",
        object_id="thread-1",
        portal_id="47354717",
        hubspot_thread_id="thread-1",
        message_id="message-1",
        deduplication_key=canonical_hubspot_message_key("47354717", "thread-1", "message-1"),
        delivery_method="webhook",
        payload={"raw": True},
    )
    client = Mock()
    client.get_conversation_thread.return_value = {"id": "thread-1", "status": "OPEN"}
    client.get_conversation_message.return_value = {
        "id": "message-1",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "hello",
        "createdAt": "2026-08-22T15:00:00Z",
        "senders": [{"actorId": "V-1"}],
    }
    with (
        patch("apps.webhooks.reconciliation.get_hubspot_client", return_value=client),
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
    ):
        assert hydrate_webhook_message_event(str(event.pk)) is True
    event.refresh_from_db()
    assert event.processing_status == WebhookEvent.ProcessingStatus.READY


@pytest.mark.django_db
def test_webhook_hydration_records_provider_failure() -> None:
    event = WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id="provider-1",
        object_id="thread-1",
        portal_id="47354717",
        hubspot_thread_id="thread-1",
        message_id="message-1",
        deduplication_key="key-failure",
        delivery_method="webhook",
        payload={},
    )
    client = Mock()
    client.get_conversation_thread.side_effect = RuntimeError("provider down")
    with patch("apps.webhooks.reconciliation.get_hubspot_client", return_value=client), pytest.raises(RuntimeError):
        hydrate_webhook_message_event(str(event.pk))
    event.refresh_from_db()
    assert event.processing_status == WebhookEvent.ProcessingStatus.ERROR
    assert "RuntimeError" in event.error_message
