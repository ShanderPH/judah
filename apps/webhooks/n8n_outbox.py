"""Concurrent-safe transactional outbox delivery to n8n."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import httpx
import structlog
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.webhooks.metrics import emit_metric
from apps.webhooks.models import N8nThreadDeliveryLock, OutboxEvent

logger = structlog.get_logger(__name__)

FailureKind = Literal[
    "authentication_configuration",
    "rate_limit",
    "n8n_error",
    "timeout",
    "connection",
    "payload_rejected",
    "invalid_response",
]


@dataclass(frozen=True, slots=True)
class ClaimedDelivery:
    """Values copied while a short database claim lock is held."""

    outbox_id: str
    event_id: str
    idempotency_key: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    thread_id: str


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    """Classified failure used by durable retry state transitions."""

    kind: FailureKind
    message: str
    retryable: bool
    http_status: int | None = None
    configuration_missing: bool = False


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize an immutable outbox body deterministically."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """Create the documented HMAC-SHA256 signature over exact request bytes."""
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def retry_delay_seconds(attempt: int) -> float:
    """Return capped exponential backoff plus full jitter."""
    base = max(float(settings.N8N_BOT_RETRY_BASE_SECONDS), 0.1)
    cap = max(float(settings.N8N_BOT_RETRY_MAX_SECONDS), base)
    exponential = min(base * (2 ** max(attempt - 1, 0)), cap)
    return min(exponential + random.uniform(0, exponential), cap)


def _processing_stale_seconds() -> float:
    """Keep lease recovery safely beyond the configured HTTP timeout budget."""
    configured = float(settings.N8N_BOT_PROCESSING_STALE_SECONDS)
    network_budget = (
        2 * (float(settings.N8N_BOT_CONNECT_TIMEOUT_SECONDS) + float(settings.N8N_BOT_READ_TIMEOUT_SECONDS)) + 30.0
    )
    return max(configured, network_budget)


def _thread_id(event: OutboxEvent) -> str:
    """Return the canonical HubSpot thread identifier for a delivery."""
    data = event.payload.get("data") if isinstance(event.payload, dict) else None
    hubspot = data.get("hubspot") if isinstance(data, dict) else None
    payload_thread_id = hubspot.get("thread_id") if isinstance(hubspot, dict) else None
    return str(payload_thread_id or event.webhook_event.hubspot_thread_id or "").strip()


def _release_thread_lease(claim: ClaimedDelivery) -> None:
    """Release only the lease still owned by this delivery claim."""
    lease = N8nThreadDeliveryLock.objects.select_for_update().filter(hubspot_thread_id=claim.thread_id).first()
    if lease is None or str(lease.current_outbox_id or "") != claim.outbox_id:
        return
    lease.current_outbox = None
    lease.locked_at = None
    lease.save(update_fields=["current_outbox", "locked_at", "updated_at"])


def claim_outbox_event(outbox_id: str) -> ClaimedDelivery | None:
    """Claim one due outbox row without retaining the lock during HTTP I/O."""
    now = timezone.now()
    stale_before = now - timedelta(seconds=_processing_stale_seconds())
    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().select_related("webhook_event").filter(pk=outbox_id).first()
        if event is None or event.status in {
            OutboxEvent.Status.DELIVERED,
            OutboxEvent.Status.DEAD_LETTER,
            OutboxEvent.Status.CANCELLED,
        }:
            return None
        if event.status == OutboxEvent.Status.PROCESSING and event.locked_at and event.locked_at > stale_before:
            return None
        if event.available_at > now:
            return None
        thread_id = _thread_id(event)
        if not thread_id:
            logger.error(
                "n8n_outbox_missing_thread_id",
                event_id=str(event.webhook_event_id),
                outbox_id=str(event.pk),
            )
            return None
        lease, _created = N8nThreadDeliveryLock.objects.select_for_update().get_or_create(hubspot_thread_id=thread_id)
        if (
            lease.current_outbox_id is not None
            and lease.current_outbox_id != event.pk
            and lease.locked_at is not None
            and lease.locked_at > stale_before
        ):
            return None
        lease.current_outbox = event
        lease.locked_at = now
        lease.save(update_fields=["current_outbox", "locked_at", "updated_at"])
        event.status = OutboxEvent.Status.PROCESSING
        event.locked_at = now
        event.attempt_count += 1
        event.save(update_fields=["status", "locked_at", "attempt_count", "updated_at"])
        return ClaimedDelivery(
            outbox_id=str(event.pk),
            event_id=str(event.webhook_event_id),
            idempotency_key=event.idempotency_key,
            payload=event.payload,
            attempt=event.attempt_count,
            max_attempts=event.max_attempts,
            thread_id=thread_id,
        )


def _headers(claim: ClaimedDelivery, body: bytes, timestamp: str, secret: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Judah-Event-Id": claim.event_id,
        "X-Idempotency-Key": claim.idempotency_key,
        "X-Judah-Timestamp": timestamp,
        "X-Judah-Signature": sign_payload(secret, timestamp, body),
        "X-Delivery-Attempt": str(claim.attempt),
    }


def _validate_success(response: httpx.Response, event_id: str) -> DeliveryFailure | None:
    try:
        body = response.json()
    except ValueError:
        return DeliveryFailure("invalid_response", "n8n returned non-JSON success body", True, response.status_code)
    if not isinstance(body, dict) or body.get("status") != "accepted" or str(body.get("event_id") or "") != event_id:
        return DeliveryFailure("invalid_response", "n8n acceptance contract was invalid", True, response.status_code)
    return None


def _classify_response(response: httpx.Response, event_id: str) -> DeliveryFailure | None:
    if 200 <= response.status_code < 300:
        return _validate_success(response, event_id)
    if response.status_code == 429:
        return DeliveryFailure("rate_limit", "n8n rate limited delivery", True, response.status_code)
    if response.status_code >= 500 or response.status_code in {408, 425}:
        return DeliveryFailure("n8n_error", "n8n transient server error", True, response.status_code)
    if response.status_code in {401, 403}:
        return DeliveryFailure(
            "authentication_configuration", "n8n rejected authentication", True, response.status_code
        )
    return DeliveryFailure("payload_rejected", "n8n rejected the payload", False, response.status_code)


def _record_success(claim: ClaimedDelivery, latency_seconds: float, http_status: int) -> None:
    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().get(pk=claim.outbox_id)
        if event.status == OutboxEvent.Status.DELIVERED:
            _release_thread_lease(claim)
            return
        event.status = OutboxEvent.Status.DELIVERED
        event.delivered_at = timezone.now()
        event.locked_at = None
        event.last_error = ""
        event.last_http_status = http_status
        event.save()
        _release_thread_lease(claim)
    emit_metric("n8n_delivery_success_total")
    emit_metric("n8n_delivery_latency_seconds", latency_seconds, kind="histogram")


def _record_failure(claim: ClaimedDelivery, failure: DeliveryFailure) -> None:
    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().get(pk=claim.outbox_id)
        if event.status == OutboxEvent.Status.DELIVERED:
            _release_thread_lease(claim)
            return
        exhausted = claim.attempt >= claim.max_attempts
        if failure.configuration_missing:
            event.attempt_count = max(event.attempt_count - 1, 0)
            exhausted = False
        if not failure.retryable or exhausted:
            event.status = OutboxEvent.Status.DEAD_LETTER
            event.dead_lettered_at = timezone.now()
            event.available_at = timezone.now()
        else:
            event.status = OutboxEvent.Status.RETRY_SCHEDULED
            event.available_at = timezone.now() + timedelta(seconds=retry_delay_seconds(max(claim.attempt, 1)))
        event.locked_at = None
        event.last_error = f"{failure.kind}: {failure.message}"
        event.last_http_status = failure.http_status
        event.save()
        _release_thread_lease(claim)
    emit_metric(
        "n8n_delivery_dead_letter_total"
        if event.status == OutboxEvent.Status.DEAD_LETTER
        else "n8n_delivery_retry_total",
        failure_kind=failure.kind,
    )


def deliver_outbox_event(outbox_id: str) -> bool:
    """Attempt one n8n delivery and durably record its classified outcome."""
    claim = claim_outbox_event(outbox_id)
    if claim is None:
        return False
    emit_metric("n8n_delivery_attempts_total", delivery_attempt=claim.attempt)

    url = str(settings.N8N_BOT_INBOUND_URL or "").strip()
    secret = str(settings.JUDAH_N8N_HMAC_SECRET or "")
    if not url or not secret:
        _record_failure(
            claim,
            DeliveryFailure(
                "authentication_configuration",
                "n8n URL or HMAC secret is not configured",
                True,
                configuration_missing=True,
            ),
        )
        return False

    body = serialize_payload(claim.payload)
    timestamp = str(int(time.time()))
    started = time.perf_counter()
    try:
        response = httpx.post(
            url,
            content=body,
            headers=_headers(claim, body, timestamp, secret),
            timeout=httpx.Timeout(
                connect=settings.N8N_BOT_CONNECT_TIMEOUT_SECONDS,
                read=settings.N8N_BOT_READ_TIMEOUT_SECONDS,
                write=settings.N8N_BOT_READ_TIMEOUT_SECONDS,
                pool=settings.N8N_BOT_CONNECT_TIMEOUT_SECONDS,
            ),
        )
    except httpx.TimeoutException:
        failure = DeliveryFailure("timeout", "n8n delivery timed out", True)
    except httpx.RequestError:
        failure = DeliveryFailure("connection", "n8n connection failed", True)
    else:
        failure = _classify_response(response, claim.event_id)

    latency = time.perf_counter() - started
    if failure is None:
        _record_success(claim, latency, response.status_code)
        logger.info(
            "n8n_outbox_delivered",
            event_id=claim.event_id,
            outbox_id=claim.outbox_id,
            idempotency_key=claim.idempotency_key,
            delivery_attempt=claim.attempt,
        )
        return True

    _record_failure(claim, failure)
    logger.warning(
        "n8n_outbox_delivery_failed",
        event_id=claim.event_id,
        outbox_id=claim.outbox_id,
        idempotency_key=claim.idempotency_key,
        delivery_attempt=claim.attempt,
        failure_kind=failure.kind,
        retryable=failure.retryable,
        http_status=failure.http_status,
    )
    return False


def due_outbox_ids(limit: int) -> list[str]:
    """Claim-neutral selection used by the periodic dispatcher safety net."""
    now = timezone.now()
    stale_before = now - timedelta(seconds=_processing_stale_seconds())
    with transaction.atomic():
        rows = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status__in=[OutboxEvent.Status.PENDING, OutboxEvent.Status.RETRY_SCHEDULED])
                | Q(status=OutboxEvent.Status.PROCESSING, locked_at__lte=stale_before),
                available_at__lte=now,
            )
            .order_by("available_at", "created_at")[:limit]
        )
        return [str(row.pk) for row in rows]


def pending_outbox_count() -> int:
    """Return the current actionable backlog size."""
    return OutboxEvent.objects.filter(
        status__in=[OutboxEvent.Status.PENDING, OutboxEvent.Status.RETRY_SCHEDULED, OutboxEvent.Status.PROCESSING]
    ).count()


__all__ = [
    "claim_outbox_event",
    "deliver_outbox_event",
    "due_outbox_ids",
    "pending_outbox_count",
    "retry_delay_seconds",
    "serialize_payload",
    "sign_payload",
]
