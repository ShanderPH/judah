"""HubSpot message hydration and periodic reconciliation workers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ai_agents.models import ConversationInstance
from apps.integrations.hubspot.client import get_hubspot_client
from apps.webhooks.metrics import emit_metric
from apps.webhooks.models import HubSpotReconciliationCursor, WebhookEvent
from apps.webhooks.n8n_inbound import ingest_hubspot_message

logger = structlog.get_logger(__name__)

_TERMINAL_STATES = {
    ConversationInstance.State.RESOLVED_BY_AI,
    ConversationInstance.State.RESOLVED_BY_HUMAN,
    ConversationInstance.State.CLOSED,
    ConversationInstance.State.FAILED_TERMINAL,
    ConversationInstance.State.IGNORED,
}


def hydrate_webhook_message_event(event_id: str) -> bool:
    """Fetch the full HubSpot objects then use the canonical ingestion service."""
    event = WebhookEvent.objects.filter(pk=event_id).first()
    if event is None:
        return False
    if event.processing_status in {WebhookEvent.ProcessingStatus.READY, WebhookEvent.ProcessingStatus.IGNORED}:
        return True
    if not event.portal_id or not event.hubspot_thread_id or not event.message_id:
        return False
    client = get_hubspot_client()
    try:
        thread = client.get_conversation_thread(event.hubspot_thread_id)
        message = client.get_conversation_message(event.hubspot_thread_id, str(event.message_id))
        ingest_hubspot_message(
            portal_id=event.portal_id,
            thread=thread,
            message=message,
            delivery_method=WebhookEvent.DeliveryMethod.WEBHOOK,
            raw_payload=event.payload,
            existing_event_id=str(event.pk),
        )
    except Exception as exc:
        WebhookEvent.objects.filter(pk=event.pk).exclude(
            processing_status__in={
                WebhookEvent.ProcessingStatus.READY,
                WebhookEvent.ProcessingStatus.IGNORED,
            }
        ).update(
            processing_status=WebhookEvent.ProcessingStatus.ERROR,
            error_message=f"{type(exc).__name__}: {exc}"[:2000],
        )
        logger.warning(
            "hubspot_message_hydration_failed",
            event_id=str(event.pk),
            idempotency_key=event.deduplication_key,
            thread_id=event.hubspot_thread_id,
            message_id=event.message_id,
            delivery_method="webhook",
            error_type=type(exc).__name__,
        )
        raise
    return True


def ensure_active_reconciliation_cursors(limit: int) -> list[str]:
    """Materialize durable cursors only for non-terminal operational threads."""
    instances = list(
        ConversationInstance.objects.exclude(state__in=_TERMINAL_STATES)
        .exclude(hubspot_thread_id__isnull=True)
        .exclude(hubspot_thread_id="")
        .order_by("last_activity_at", "created_at")[:limit]
    )
    cursor_ids: list[str] = []
    for instance in instances:
        try:
            cursor, _created = HubSpotReconciliationCursor.objects.get_or_create(
                conversation_instance=instance,
                defaults={"hubspot_thread_id": str(instance.hubspot_thread_id)},
            )
        except IntegrityError:
            cursor = HubSpotReconciliationCursor.objects.get(hubspot_thread_id=instance.hubspot_thread_id)
        cursor_ids.append(str(cursor.pk))
    return cursor_ids


def _claim_cursor(cursor_id: str) -> str | None:
    now = timezone.now()
    stale_before = now - timedelta(seconds=settings.N8N_BOT_PROCESSING_STALE_SECONDS)
    with transaction.atomic():
        cursor = (
            HubSpotReconciliationCursor.objects.select_for_update(skip_locked=True)
            .filter(pk=cursor_id)
            .filter(Q(locked_at__isnull=True) | Q(locked_at__lte=stale_before))
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .first()
        )
        if cursor is None:
            return None
        cursor.locked_at = now
        cursor.save(update_fields=["locked_at", "updated_at"])
        return cursor.hubspot_thread_id


def _created_at(message: dict[str, Any]):
    value = message.get("createdAt")
    return parse_datetime(str(value)) if value else None


def _record_cursor_success(cursor_id: str, message: dict[str, Any] | None = None) -> None:
    with transaction.atomic():
        cursor = HubSpotReconciliationCursor.objects.select_for_update().get(pk=cursor_id)
        if message is not None:
            created_at = _created_at(message)
            candidate = (created_at, str(message.get("id") or ""))
            current = (cursor.last_message_created_at, cursor.last_message_id)
            if current[0] is None or (candidate[0] is not None and candidate >= current):
                cursor.last_message_created_at = created_at
                cursor.last_message_id = candidate[1]
        cursor.last_reconciled_at = timezone.now()
        cursor.last_error = ""
        cursor.next_attempt_at = None
        cursor.locked_at = None
        cursor.save()


def _record_cursor_failure(cursor_id: str, exc: Exception) -> None:
    HubSpotReconciliationCursor.objects.filter(pk=cursor_id).update(
        last_error=f"{type(exc).__name__}: {exc}"[:2000],
        next_attempt_at=timezone.now() + timedelta(seconds=settings.N8N_BOT_RECONCILIATION_INTERVAL_SECONDS),
        locked_at=None,
    )


def reconcile_cursor(cursor_id: str) -> int:
    """Reconcile one claimed thread, stopping before any failed message."""
    thread_id = _claim_cursor(cursor_id)
    if thread_id is None:
        return 0
    cursor = HubSpotReconciliationCursor.objects.select_related("conversation_instance").get(pk=cursor_id)
    portal_id = str(settings.HUBSPOT_PORTAL_ID or "").strip()
    if not portal_id:
        exc = RuntimeError("HUBSPOT_PORTAL_ID is required for reconciliation.")
        _record_cursor_failure(cursor_id, exc)
        raise exc

    client = get_hubspot_client()
    processed = 0
    try:
        thread = client.get_conversation_thread(thread_id)
        if bool(thread.get("spam")) or str(thread.get("status") or "").upper() == "CLOSED":
            _record_cursor_success(cursor_id)
            return 0

        messages: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            page, after = client.list_conversation_messages_page(thread_id, after=after, limit=100)
            messages.extend(page)
            if not after:
                break
        messages.sort(key=lambda item: (str(item.get("createdAt") or ""), str(item.get("id") or "")))

        cutoff = None
        if cursor.last_message_created_at:
            cutoff = cursor.last_message_created_at - timedelta(
                seconds=settings.N8N_BOT_RECONCILIATION_LOOKBACK_SECONDS
            )
        for message in messages:
            created_at = _created_at(message)
            if cutoff and created_at and created_at < cutoff:
                continue
            ingest_hubspot_message(
                portal_id=portal_id,
                thread=thread,
                message=message,
                delivery_method=WebhookEvent.DeliveryMethod.RECONCILIATION,
                raw_payload=message,
            )
            _record_cursor_success(cursor_id, message)
            processed += 1
            if created_at:
                ConversationInstance.objects.filter(pk=cursor.conversation_instance_id).filter(
                    Q(last_activity_at__isnull=True) | Q(last_activity_at__lt=created_at)
                ).update(last_activity_at=created_at, last_message_id=str(message.get("id") or ""))
        _record_cursor_success(cursor_id)
    except Exception as exc:
        _record_cursor_failure(cursor_id, exc)
        emit_metric("hubspot_reconciliation_failures_total", thread_id=thread_id)
        logger.warning(
            "hubspot_reconciliation_failed",
            thread_id=thread_id,
            delivery_method="reconciliation",
            error_type=type(exc).__name__,
        )
        raise
    return processed


def reconcile_active_threads() -> int:
    """Run one bounded reconciliation pass when the feature flag is enabled."""
    if not settings.N8N_BOT_RECONCILIATION_ENABLED:
        logger.info("hubspot_reconciliation_disabled")
        return 0
    emit_metric("hubspot_reconciliation_runs_total")
    total = 0
    cursor_ids = ensure_active_reconciliation_cursors(settings.N8N_BOT_RECONCILIATION_BATCH_SIZE)
    for cursor_id in cursor_ids:
        try:
            total += reconcile_cursor(cursor_id)
        except Exception:
            continue
    return total


__all__ = [
    "ensure_active_reconciliation_cursors",
    "hydrate_webhook_message_event",
    "reconcile_active_threads",
    "reconcile_cursor",
]
