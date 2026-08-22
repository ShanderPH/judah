"""n8n delivery contract, HMAC, retry, and dead-letter tests."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from django.test import override_settings
from django.utils import timezone

from apps.webhooks.models import N8nThreadDeliveryLock, OutboxEvent, WebhookEvent
from apps.webhooks.n8n_outbox import claim_outbox_event, deliver_outbox_event, serialize_payload, sign_payload


def _outbox(max_attempts: int = 3, *, suffix: str = "1", thread_id: str = "thread-1") -> OutboxEvent:
    event = WebhookEvent.objects.create(
        source="hubspot",
        event_type="conversation.newMessage",
        event_id=f"provider-{suffix}",
        object_id=thread_id,
        hubspot_thread_id=thread_id,
        deduplication_key=f"key-{suffix}",
        payload={},
    )
    return OutboxEvent.objects.create(
        webhook_event=event,
        event_type="conversation.newMessage",
        idempotency_key=f"key-{suffix}",
        payload={
            "action": "PROCESS_NEW_MESSAGE",
            "data": {
                "event": {"event_id": str(event.pk)},
                "hubspot": {"thread_id": thread_id},
            },
        },
        max_attempts=max_attempts,
        available_at=timezone.now(),
    )


def test_deterministic_body_and_hmac() -> None:
    body = serialize_payload({"b": 2, "a": "ç"})
    assert body == b'{"a":"\xc3\xa7","b":2}'
    assert sign_payload("secret", "100", body).startswith("sha256=")
    assert sign_payload("secret", "100", body) == sign_payload("secret", "100", body)


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="https://n8n.example.test/webhook",
    JUDAH_N8N_HMAC_SECRET="secret",
    N8N_BOT_CONNECT_TIMEOUT_SECONDS=1,
    N8N_BOT_READ_TIMEOUT_SECONDS=2,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
)
def test_success_sends_exact_body_and_required_headers() -> None:
    outbox = _outbox()

    def accepted(_url, **kwargs):
        assert kwargs["content"] == serialize_payload(outbox.payload)
        headers = kwargs["headers"]
        assert headers["X-Judah-Event-Id"] == str(outbox.webhook_event_id)
        assert headers["X-Idempotency-Key"] == "key-1"
        assert headers["X-Delivery-Attempt"] == "1"
        assert headers["X-Judah-Signature"].startswith("sha256=")
        return httpx.Response(202, json={"status": "accepted", "event_id": str(outbox.webhook_event_id)})

    with patch("apps.webhooks.n8n_outbox.httpx.post", side_effect=accepted):
        assert deliver_outbox_event(str(outbox.pk)) is True

    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.DELIVERED
    lease = N8nThreadDeliveryLock.objects.get(hubspot_thread_id="thread-1")
    assert lease.current_outbox_id is None
    assert lease.locked_at is None


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="https://n8n.example.test/webhook",
    JUDAH_N8N_HMAC_SECRET="secret",
    N8N_BOT_CONNECT_TIMEOUT_SECONDS=1,
    N8N_BOT_READ_TIMEOUT_SECONDS=2,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
    N8N_BOT_RETRY_BASE_SECONDS=1,
    N8N_BOT_RETRY_MAX_SECONDS=10,
)
@pytest.mark.parametrize("status", [429, 500])
def test_transient_http_failures_schedule_retry(status: int) -> None:
    outbox = _outbox()
    with patch("apps.webhooks.n8n_outbox.httpx.post", return_value=httpx.Response(status)):
        assert deliver_outbox_event(str(outbox.pk)) is False
    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.RETRY_SCHEDULED
    assert outbox.attempt_count == 1
    assert N8nThreadDeliveryLock.objects.get(hubspot_thread_id="thread-1").current_outbox_id is None


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="https://n8n.example.test/webhook",
    JUDAH_N8N_HMAC_SECRET="secret",
    N8N_BOT_CONNECT_TIMEOUT_SECONDS=1,
    N8N_BOT_READ_TIMEOUT_SECONDS=2,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
)
def test_non_retryable_400_dead_letters_immediately() -> None:
    outbox = _outbox()
    with patch("apps.webhooks.n8n_outbox.httpx.post", return_value=httpx.Response(400)):
        assert deliver_outbox_event(str(outbox.pk)) is False
    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.DEAD_LETTER
    assert outbox.dead_lettered_at is not None


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="",
    JUDAH_N8N_HMAC_SECRET="",
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
    N8N_BOT_RETRY_BASE_SECONDS=1,
    N8N_BOT_RETRY_MAX_SECONDS=10,
)
def test_missing_configuration_keeps_event_retryable_without_consuming_attempt() -> None:
    outbox = _outbox(max_attempts=1)
    assert deliver_outbox_event(str(outbox.pk)) is False
    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.RETRY_SCHEDULED
    assert outbox.attempt_count == 0


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="https://n8n.example.test/webhook",
    JUDAH_N8N_HMAC_SECRET="secret",
    N8N_BOT_CONNECT_TIMEOUT_SECONDS=1,
    N8N_BOT_READ_TIMEOUT_SECONDS=2,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
    N8N_BOT_RETRY_BASE_SECONDS=1,
    N8N_BOT_RETRY_MAX_SECONDS=10,
)
@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
def test_transport_failures_are_retryable(failure: Exception) -> None:
    outbox = _outbox()
    with patch("apps.webhooks.n8n_outbox.httpx.post", side_effect=failure):
        assert deliver_outbox_event(str(outbox.pk)) is False
    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.RETRY_SCHEDULED


@pytest.mark.django_db
@override_settings(
    N8N_BOT_INBOUND_URL="https://n8n.example.test/webhook",
    JUDAH_N8N_HMAC_SECRET="secret",
    N8N_BOT_CONNECT_TIMEOUT_SECONDS=1,
    N8N_BOT_READ_TIMEOUT_SECONDS=2,
    N8N_BOT_PROCESSING_STALE_SECONDS=60,
    N8N_BOT_RETRY_BASE_SECONDS=1,
    N8N_BOT_RETRY_MAX_SECONDS=10,
)
def test_invalid_success_contract_retries_and_exhaustion_dead_letters() -> None:
    outbox = _outbox(max_attempts=1)
    response = httpx.Response(202, json={"status": "accepted", "event_id": "wrong"})
    with patch("apps.webhooks.n8n_outbox.httpx.post", return_value=response):
        assert deliver_outbox_event(str(outbox.pk)) is False
    outbox.refresh_from_db()
    assert outbox.status == OutboxEvent.Status.DEAD_LETTER


@pytest.mark.django_db
@override_settings(N8N_BOT_PROCESSING_STALE_SECONDS=60)
def test_thread_lease_blocks_second_outbox_for_same_thread() -> None:
    first = _outbox(suffix="first", thread_id="thread-shared")
    second = _outbox(suffix="second", thread_id="thread-shared")

    first_claim = claim_outbox_event(str(first.pk))

    assert first_claim is not None
    assert claim_outbox_event(str(second.pk)) is None
    lease = N8nThreadDeliveryLock.objects.get(hubspot_thread_id="thread-shared")
    assert lease.current_outbox_id == first.pk


@pytest.mark.django_db
@override_settings(N8N_BOT_PROCESSING_STALE_SECONDS=60)
def test_thread_lease_keeps_different_threads_parallel() -> None:
    first = _outbox(suffix="first", thread_id="thread-a")
    second = _outbox(suffix="second", thread_id="thread-b")

    assert claim_outbox_event(str(first.pk)) is not None
    assert claim_outbox_event(str(second.pk)) is not None
