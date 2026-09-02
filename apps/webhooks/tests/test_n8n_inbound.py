"""Atomic, canonical HubSpot message ingestion tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.webhooks.models import OutboxEvent, WebhookEvent
from apps.webhooks.n8n_inbound import (
    canonical_hubspot_message_key,
    ingest_hubspot_message,
    record_hubspot_message_envelope,
)


def _thread() -> dict:
    return {
        "id": "thread-1",
        "status": "OPEN",
        "associatedContactId": "contact-1",
        "originalChannelId": "1007",
        "originalChannelAccountId": "account-1",
        "threadAssociations": {"associatedTicketId": "ticket-1"},
    }


def _message(**overrides) -> dict:
    message = {
        "id": "message-1",
        "conversationsThreadId": "thread-1",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "Preciso de ajuda",
        "createdAt": "2026-08-22T15:00:00Z",
        "channelId": "1007",
        "channelAccountId": "account-1",
        "senders": [{"actorId": "V-1"}],
    }
    message.update(overrides)
    return message


def test_canonical_key_matches_mandated_formula() -> None:
    import hashlib

    expected = hashlib.sha256(b"hubspot:47354717:thread-1:message-1").hexdigest()
    assert canonical_hubspot_message_key("47354717", "thread-1", "message-1") == expected


@pytest.mark.django_db
@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=8)
def test_webhook_and_reconciliation_converge_to_one_ledger_and_outbox() -> None:
    envelope = {
        "portalId": "47354717",
        "objectId": "thread-1",
        "messageId": "message-1",
        "eventId": "event-1",
    }
    first = record_hubspot_message_envelope(envelope)
    with patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"):
        hydrated = ingest_hubspot_message(
            portal_id="47354717",
            thread=_thread(),
            message=_message(),
            delivery_method="webhook",
            raw_payload=envelope,
            existing_event_id=first.event_id,
        )
        reconciled = ingest_hubspot_message(
            portal_id="47354717",
            thread=_thread(),
            message=_message(),
            delivery_method="reconciliation",
            raw_payload=_message(),
        )

    assert first.event_id == hydrated.event_id == reconciled.event_id
    assert reconciled.duplicate is True
    assert WebhookEvent.objects.count() == 1
    assert OutboxEvent.objects.count() == 1
    payload = OutboxEvent.objects.get().payload
    assert payload["action"] == "PROCESS_NEW_MESSAGE"
    assert isinstance(payload["data"], dict)
    assert payload["data"]["metadata"]["idempotency_key"] == OutboxEvent.objects.get().idempotency_key
    assert "triage" not in payload["data"]
    assert "customer_identity" not in payload["data"]


@pytest.mark.django_db
@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=8)
def test_existing_envelope_hydration_does_not_insert_another_ledger_row() -> None:
    envelope = {
        "portalId": "47354717",
        "objectId": "thread-1",
        "messageId": "message-1",
        "eventId": "event-1",
    }
    first = record_hubspot_message_envelope(envelope)

    with (
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
        CaptureQueriesContext(connection) as queries,
    ):
        result = ingest_hubspot_message(
            portal_id="47354717",
            thread=_thread(),
            message=_message(),
            delivery_method="webhook",
            raw_payload=envelope,
            existing_event_id=first.event_id,
        )

    ledger_inserts = [
        query["sql"] for query in queries.captured_queries if 'INSERT INTO "webhook_events"' in query["sql"]
    ]
    assert ledger_inserts == []
    assert result.event_id == first.event_id
    assert WebhookEvent.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db
def test_real_webhook_retry_reuses_the_existing_envelope() -> None:
    envelope = {
        "portalId": "47354717",
        "objectId": "thread-1",
        "messageId": "message-1",
        "eventId": "event-1",
    }

    first = record_hubspot_message_envelope(envelope)
    with CaptureQueriesContext(connection) as queries:
        retried = record_hubspot_message_envelope(envelope)

    assert retried.event_id == first.event_id
    assert retried.duplicate is True
    assert WebhookEvent.objects.count() == 1
    insert_sql = [query["sql"] for query in queries.captured_queries if "webhook_events" in query["sql"]]
    expected_conflict_clause = "ON CONFLICT" if connection.vendor == "postgresql" else "INSERT OR IGNORE"
    assert any(expected_conflict_clause in sql for sql in insert_sql)


@pytest.mark.django_db
@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=8)
def test_event_update_rolls_back_when_outbox_creation_fails() -> None:
    envelope = {
        "portalId": "47354717",
        "objectId": "thread-1",
        "messageId": "message-1",
        "eventId": "event-1",
    }
    first = record_hubspot_message_envelope(envelope)

    with (
        patch.object(OutboxEvent.objects, "get_or_create", side_effect=RuntimeError("outbox unavailable")),
        pytest.raises(RuntimeError, match="outbox unavailable"),
    ):
        ingest_hubspot_message(
            portal_id="47354717",
            thread=_thread(),
            message=_message(),
            delivery_method="webhook",
            raw_payload=envelope,
            existing_event_id=first.event_id,
        )

    event = WebhookEvent.objects.get(pk=first.event_id)
    assert event.processing_status == WebhookEvent.ProcessingStatus.RECEIVED
    assert event.processed is False
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
def test_hydration_rejects_an_envelope_with_a_different_canonical_key() -> None:
    first = record_hubspot_message_envelope(
        {
            "portalId": "47354717",
            "objectId": "thread-other",
            "messageId": "message-other",
            "eventId": "event-other",
        }
    )

    with pytest.raises(ValueError, match="does not match the persisted envelope"):
        ingest_hubspot_message(
            portal_id="47354717",
            thread=_thread(),
            message=_message(),
            delivery_method="webhook",
            existing_event_id=first.event_id,
        )

    event = WebhookEvent.objects.get(pk=first.event_id)
    assert event.processing_status == WebhookEvent.ProcessingStatus.RECEIVED
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=8, N8N_BOT_SENDER_ACTOR_ID="A-bot")
@pytest.mark.parametrize(
    ("message_overrides", "reason"),
    [
        ({"direction": "OUTGOING"}, "outgoing_message"),
        ({"senders": [{"actorId": "A-bot"}]}, "bot_message"),
        ({"senders": [{"actorId": "A-agent"}]}, "agent_message"),
        ({"type": "COMMENT"}, "non_message_event"),
        ({"text": ""}, "empty_message"),
    ],
)
def test_non_customer_messages_are_audited_without_outbox(message_overrides: dict, reason: str) -> None:
    message = _message(id=f"message-{reason}", **message_overrides)
    result = ingest_hubspot_message(
        portal_id="47354717",
        thread=_thread(),
        message=message,
        delivery_method="reconciliation",
    )

    assert result.ignored is True
    assert result.ignored_reason == reason
    assert OutboxEvent.objects.count() == 0
    assert WebhookEvent.objects.get(pk=result.event_id).ignored_reason == reason


@pytest.mark.django_db
def test_missing_message_id_is_explicitly_ignored() -> None:
    result = record_hubspot_message_envelope({"portalId": "1", "objectId": "thread-1"})
    assert result.ignored is True
    assert result.idempotency_key is None
    assert WebhookEvent.objects.get(pk=result.event_id).ignored_reason == "missing_canonical_identifier"
