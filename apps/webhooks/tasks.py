"""Durable webhook processing tasks."""

from __future__ import annotations

import structlog

from apps.webhooks.models import WebhookEvent
from apps.webhooks.services import MAX_RETRIES, process_webhook_event
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=MAX_RETRIES - 1,
    default_retry_delay=10,
    name="webhooks.process_webhook_event_task",
)
def process_webhook_event_task(self, event_id: str) -> bool:
    """Process a persisted webhook with bounded exponential retry."""
    ok = process_webhook_event(event_id)
    if ok:
        return True

    event = WebhookEvent.objects.filter(pk=event_id).first()
    if event is None or event.retry_count >= MAX_RETRIES:
        return False

    countdown = min(10 * (2**self.request.retries), 120)
    logger.warning(
        "webhook_processing_retry_scheduled",
        event_id=event_id,
        retry=self.request.retries,
        countdown=countdown,
    )
    raise self.retry(
        exc=RuntimeError(event.error_message or "Webhook processing failed."),
        countdown=countdown,
    )


__all__ = ["process_webhook_event_task"]
