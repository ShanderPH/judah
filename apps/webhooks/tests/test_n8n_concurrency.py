"""PostgreSQL-only contention tests for canonical ingestion and outbox claims."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone

from apps.webhooks.models import OutboxEvent, WebhookEvent
from apps.webhooks.n8n_inbound import ingest_hubspot_message, record_hubspot_message_envelope
from apps.webhooks.n8n_outbox import claim_outbox_event

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="requires PostgreSQL row-level locking"),
]


@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=3, N8N_BOT_PROCESSING_STALE_SECONDS=60)
def test_equal_messages_from_two_workers_create_one_outbox() -> None:
    barrier = Barrier(2)
    thread = {"id": "thread-concurrent", "status": "OPEN"}
    message = {
        "id": "message-concurrent",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "hello",
        "createdAt": "2026-08-22T15:00:00Z",
        "senders": [{"actorId": "V-1"}],
    }

    def ingest(method: str) -> str:
        close_old_connections()
        barrier.wait()
        try:
            return ingest_hubspot_message(
                portal_id="portal-1",
                thread=thread,
                message=message,
                delivery_method=method,
            ).event_id
        finally:
            close_old_connections()

    with (
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        event_ids = list(executor.map(ingest, ["webhook", "reconciliation"]))

    assert event_ids[0] == event_ids[1]
    assert WebhookEvent.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=3)
def test_two_hydrations_of_one_envelope_create_one_outbox() -> None:
    first = record_hubspot_message_envelope(
        {
            "portalId": "portal-1",
            "objectId": "thread-hydration",
            "messageId": "message-hydration",
            "eventId": "provider-1",
        }
    )
    barrier = Barrier(2)
    thread = {"id": "thread-hydration", "status": "OPEN"}
    message = {
        "id": "message-hydration",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "hello",
        "createdAt": "2026-08-22T15:00:00Z",
        "senders": [{"actorId": "V-1"}],
    }

    def hydrate(_index: int) -> str:
        close_old_connections()
        barrier.wait()
        try:
            return ingest_hubspot_message(
                portal_id="portal-1",
                thread=thread,
                message=message,
                delivery_method="webhook",
                existing_event_id=first.event_id,
            ).event_id
        finally:
            close_old_connections()

    with (
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        event_ids = list(executor.map(hydrate, [1, 2]))

    assert event_ids == [first.event_id, first.event_id]
    assert WebhookEvent.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


@override_settings(N8N_BOT_MAX_DELIVERY_ATTEMPTS=3)
def test_hydration_and_reconciliation_converge_on_existing_envelope() -> None:
    first = record_hubspot_message_envelope(
        {
            "portalId": "portal-1",
            "objectId": "thread-race",
            "messageId": "message-race",
            "eventId": "provider-1",
        }
    )
    barrier = Barrier(2)
    thread = {"id": "thread-race", "status": "OPEN"}
    message = {
        "id": "message-race",
        "type": "MESSAGE",
        "direction": "INCOMING",
        "text": "hello",
        "createdAt": "2026-08-22T15:00:00Z",
        "senders": [{"actorId": "V-1"}],
    }

    def ingest(existing_event_id: str | None) -> str:
        close_old_connections()
        barrier.wait()
        try:
            return ingest_hubspot_message(
                portal_id="portal-1",
                thread=thread,
                message=message,
                delivery_method="webhook" if existing_event_id else "reconciliation",
                existing_event_id=existing_event_id,
            ).event_id
        finally:
            close_old_connections()

    with (
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay"),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        event_ids = list(executor.map(ingest, [first.event_id, None]))

    assert event_ids == [first.event_id, first.event_id]
    assert WebhookEvent.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


@override_settings(N8N_BOT_PROCESSING_STALE_SECONDS=60)
def test_two_workers_claim_one_outbox_once() -> None:
    event = WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id="provider",
        object_id="thread",
        hubspot_thread_id="thread",
        deduplication_key="claim-key",
        payload={"data": {"hubspot": {"thread_id": "thread"}}},
    )
    outbox = OutboxEvent.objects.create(
        webhook_event=event,
        event_type="conversation.newMessage",
        idempotency_key="claim-key",
        payload={},
        available_at=timezone.now(),
    )
    barrier = Barrier(2)

    def claim(_index: int):
        close_old_connections()
        barrier.wait()
        try:
            return claim_outbox_event(str(outbox.pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, [1, 2]))
    assert sum(item is not None for item in claims) == 1


@override_settings(N8N_BOT_PROCESSING_STALE_SECONDS=60)
def test_two_workers_claim_only_one_outbox_for_the_same_thread() -> None:
    outboxes = []
    for suffix in ("a", "b"):
        event = WebhookEvent.objects.create(
            source="hubspot",
            event_type="conversation.newMessage",
            event_id=f"provider-{suffix}",
            object_id="thread-shared",
            hubspot_thread_id="thread-shared",
            deduplication_key=f"claim-key-{suffix}",
            payload={},
        )
        outboxes.append(
            OutboxEvent.objects.create(
                webhook_event=event,
                event_type="conversation.newMessage",
                idempotency_key=f"claim-key-{suffix}",
                payload={"data": {"hubspot": {"thread_id": "thread-shared"}}},
                available_at=timezone.now(),
            )
        )
    barrier = Barrier(2)

    def claim(index: int):
        close_old_connections()
        barrier.wait()
        try:
            return claim_outbox_event(str(outboxes[index].pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, [0, 1]))
    assert sum(item is not None for item in claims) == 1
