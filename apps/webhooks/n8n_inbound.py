"""Canonical HubSpot message normalization and atomic n8n ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.webhooks.metrics import emit_metric
from apps.webhooks.models import OutboxEvent, WebhookEvent
from common.idempotency import canonical_event_key

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Stable outcome returned by both webhook and reconciliation callers."""

    event_id: str
    idempotency_key: str | None
    duplicate: bool
    ignored: bool
    ignored_reason: str | None
    outbox_id: str | None


def canonical_hubspot_message_key(portal_id: str, thread_id: str, message_id: str) -> str:
    """Return the one canonical identity mandated for HubSpot messages."""
    material = f"hubspot:{portal_id}:{thread_id}:{message_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _required_message_identifiers(payload: dict[str, Any]) -> tuple[str, str, str]:
    portal_id = str(payload.get("portalId") or payload.get("portal_id") or settings.HUBSPOT_PORTAL_ID or "").strip()
    thread_id = str(
        payload.get("threadId")
        or payload.get("thread_id")
        or payload.get("objectId")
        or payload.get("conversationsThreadId")
        or ""
    ).strip()
    message_id = str(payload.get("messageId") or payload.get("message_id") or payload.get("id") or "").strip()
    return portal_id, thread_id, message_id


def record_hubspot_message_envelope(payload: dict[str, Any]) -> IngestionResult:
    """Persist an authenticated webhook envelope before asynchronous hydration."""
    portal_id, thread_id, message_id = _required_message_identifiers(payload)
    if not portal_id or not thread_id or not message_id:
        fallback = canonical_event_key(source="hubspot", event_type="conversation.newMessage", payload=payload)
        event, created = WebhookEvent.objects.get_or_create(
            deduplication_key=fallback,
            defaults={
                "source": "hubspot",
                "event_type": "conversation.newMessage",
                "event_id": str(payload.get("eventId") or ""),
                "object_id": thread_id,
                "portal_id": portal_id,
                "hubspot_thread_id": thread_id,
                "message_id": message_id or None,
                "delivery_method": WebhookEvent.DeliveryMethod.WEBHOOK,
                "payload": payload,
                "processing_status": WebhookEvent.ProcessingStatus.IGNORED,
                "ignored_reason": "missing_canonical_identifier",
                "processed": True,
                "processed_at": timezone.now(),
            },
        )
        emit_metric("hubspot_messages_ignored_total", reason="missing_canonical_identifier")
        return IngestionResult(str(event.pk), None, not created, True, "missing_canonical_identifier", None)

    key = canonical_hubspot_message_key(portal_id, thread_id, message_id)
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.create(
                source="hubspot",
                event_type="conversation.newMessage",
                event_id=str(payload.get("eventId") or ""),
                object_id=thread_id,
                portal_id=portal_id,
                hubspot_thread_id=thread_id,
                message_id=message_id,
                deduplication_key=key,
                delivery_method=WebhookEvent.DeliveryMethod.WEBHOOK,
                payload=payload,
            )
        duplicate = False
    except IntegrityError:
        event = WebhookEvent.objects.get(deduplication_key=key)
        duplicate = True
        emit_metric("hubspot_messages_duplicate_total", delivery_method="webhook")

    emit_metric("hubspot_webhook_events_received_total", event_type="conversation.newMessage")
    return IngestionResult(str(event.pk), key, duplicate, False, None, None)


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = parse_datetime(str(value))
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _first_sender(message: dict[str, Any]) -> dict[str, Any]:
    senders = message.get("senders")
    if isinstance(senders, list) and senders and isinstance(senders[0], dict):
        return senders[0]
    return {}


def _ignored_reason(message: dict[str, Any]) -> str | None:
    if str(message.get("type") or "MESSAGE").upper() != "MESSAGE":
        return "non_message_event"
    if bool(message.get("archived")):
        return "archived_message"
    if str(message.get("direction") or "").upper() != "INCOMING":
        return "outgoing_message"
    sender_actor_id = str(_first_sender(message).get("actorId") or message.get("senderActorId") or "")
    configured_bot = str(settings.N8N_BOT_SENDER_ACTOR_ID or "")
    if configured_bot and sender_actor_id == configured_bot:
        return "bot_message"
    if sender_actor_id.startswith("A-"):
        return "agent_message"
    if not str(message.get("text") or "").strip():
        return "empty_message"
    return None


def _delivery_identifiers(message: dict[str, Any]) -> dict[str, Any]:
    sender = _first_sender(message)
    identifier = sender.get("deliveryIdentifier")
    if not isinstance(identifier, dict):
        return {"email": None, "phone": None, "trusted": False, "source": None}
    identifier_type = str(identifier.get("type") or "").upper()
    value = identifier.get("value")
    return {
        "email": str(value) if value and identifier_type == "EMAIL" else None,
        "phone": str(value) if value and identifier_type in {"PHONE", "PHONE_NUMBER"} else None,
        "trusted": False,
        "source": identifier_type.lower() if value and identifier_type else None,
    }


def _n8n_payload(
    *,
    event: WebhookEvent,
    message: dict[str, Any],
    thread: dict[str, Any],
    idempotency_key: str,
    delivery_method: str,
) -> dict[str, Any]:
    sender = _first_sender(message)
    associations = thread.get("threadAssociations")
    ticket_id = associations.get("associatedTicketId") if isinstance(associations, dict) else None
    occurred_at = _parse_datetime(message.get("createdAt"))
    return {
        "action": "PROCESS_NEW_MESSAGE",
        "data": {
            "schema_version": "1.0",
            "event": {
                "event_id": str(event.pk),
                "type": "conversation.newMessage",
                "message_id": str(message["id"]),
                "occurred_at": occurred_at.isoformat().replace("+00:00", "Z") if occurred_at else None,
                "source": "judah",
            },
            "hubspot": {
                "portal_id": event.portal_id,
                "thread_id": event.hubspot_thread_id,
                "ticket_id": str(ticket_id) if ticket_id is not None else None,
            },
            "conversation": {
                "threadId": event.hubspot_thread_id,
                "status": thread.get("status"),
                "associatedContactId": thread.get("associatedContactId"),
                "originalChannelId": thread.get("originalChannelId"),
                "originalChannelAccountId": thread.get("originalChannelAccountId"),
            },
            "gateway": {
                "is_incoming_customer_message": True,
                "delivery_method": delivery_method,
            },
            "message": {
                "direction": "INCOMING",
                "text": str(message.get("text") or ""),
                "created_at": occurred_at.isoformat().replace("+00:00", "Z") if occurred_at else None,
                "channel_id": message.get("channelId"),
                "channel_account_id": message.get("channelAccountId"),
                "sender_actor_id": sender.get("actorId") or message.get("senderActorId"),
            },
            "delivery_identifiers": _delivery_identifiers(message),
            "metadata": {"idempotency_key": idempotency_key, "service_cycle_id": None},
        },
    }


def ingest_hubspot_message(
    *,
    portal_id: str,
    thread: dict[str, Any],
    message: dict[str, Any],
    delivery_method: str,
    raw_payload: dict[str, Any] | None = None,
) -> IngestionResult:
    """Atomically converge webhook and reconciliation into ledger and outbox."""
    thread_id = str(thread.get("id") or message.get("conversationsThreadId") or "").strip()
    message_id = str(message.get("id") or "").strip()
    if not portal_id or not thread_id or not message_id:
        raise ValueError("HubSpot message ingestion requires portal_id, thread_id, and message_id.")

    key = canonical_hubspot_message_key(portal_id, thread_id, message_id)
    ignored_reason = _ignored_reason(message)
    duplicate = False
    with transaction.atomic():
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    source="hubspot",
                    event_type="conversation.newMessage",
                    event_id="",
                    object_id=thread_id,
                    portal_id=portal_id,
                    hubspot_thread_id=thread_id,
                    message_id=message_id,
                    deduplication_key=key,
                    delivery_method=delivery_method,
                    payload=raw_payload or message,
                )
        except IntegrityError:
            event = WebhookEvent.objects.select_for_update().get(deduplication_key=key)
            duplicate = event.processing_status in {
                WebhookEvent.ProcessingStatus.READY,
                WebhookEvent.ProcessingStatus.IGNORED,
            }

        if duplicate:
            emit_metric("hubspot_messages_duplicate_total", delivery_method=delivery_method)
            outbox = OutboxEvent.objects.filter(webhook_event=event).first()
            return IngestionResult(
                str(event.pk),
                key,
                True,
                event.processing_status == WebhookEvent.ProcessingStatus.IGNORED,
                event.ignored_reason or None,
                str(outbox.pk) if outbox else None,
            )

        occurred_at = _parse_datetime(message.get("createdAt"))
        associations = thread.get("threadAssociations")
        ticket_id = associations.get("associatedTicketId") if isinstance(associations, dict) else None
        event.hubspot_ticket_id = str(ticket_id or "")
        event.hubspot_contact_id = str(thread.get("associatedContactId") or "")
        event.occurred_at = occurred_at
        event.message_type = str(message.get("type") or "")
        event.processed = True
        event.processed_at = timezone.now()
        event.error_message = ""

        if ignored_reason:
            event.processing_status = WebhookEvent.ProcessingStatus.IGNORED
            event.ignored_reason = ignored_reason
            event.save()
            emit_metric("hubspot_messages_ignored_total", reason=ignored_reason, delivery_method=delivery_method)
            return IngestionResult(str(event.pk), key, False, True, ignored_reason, None)

        event.processing_status = WebhookEvent.ProcessingStatus.READY
        event.ignored_reason = ""
        event.save()
        payload = _n8n_payload(
            event=event,
            message=message,
            thread=thread,
            idempotency_key=key,
            delivery_method=event.delivery_method or delivery_method,
        )
        outbox, outbox_created = OutboxEvent.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "webhook_event": event,
                "destination": "n8n_bot",
                "event_type": "conversation.newMessage",
                "payload": payload,
                "max_attempts": settings.N8N_BOT_MAX_DELIVERY_ATTEMPTS,
                "available_at": timezone.now(),
            },
        )
        duplicate = not outbox_created

        if outbox_created:
            from apps.webhooks.tasks import dispatch_n8n_outbox_event_task

            def _dispatch_after_commit() -> None:
                try:
                    dispatch_n8n_outbox_event_task.delay(str(outbox.pk))
                except Exception as exc:
                    logger.warning(
                        "n8n_outbox_broker_dispatch_failed",
                        event_id=str(event.pk),
                        outbox_id=str(outbox.pk),
                        idempotency_key=key,
                        error_type=type(exc).__name__,
                    )

            transaction.on_commit(_dispatch_after_commit)

    emit_metric(
        "hubspot_messages_recovered_total"
        if delivery_method == "reconciliation"
        else "hubspot_messages_ingested_total",
        delivery_method=delivery_method,
    )
    logger.info(
        "hubspot_message_ingested",
        event_id=str(event.pk),
        outbox_id=str(outbox.pk),
        idempotency_key=key,
        thread_id=thread_id,
        ticket_id=event.hubspot_ticket_id or None,
        message_id=message_id,
        delivery_method=delivery_method,
        duplicate=duplicate,
    )
    return IngestionResult(str(event.pk), key, duplicate, False, None, str(outbox.pk))


__all__ = [
    "IngestionResult",
    "canonical_hubspot_message_key",
    "ingest_hubspot_message",
    "record_hubspot_message_envelope",
]
