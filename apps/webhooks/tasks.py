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


@shared_task(bind=True, max_retries=4, name="webhooks.hydrate_hubspot_message_event_task")
def hydrate_hubspot_message_event_task(self, event_id: str) -> bool:
    """Hydrate a persisted HubSpot message envelope with bounded retry."""
    from apps.webhooks.reconciliation import hydrate_webhook_message_event

    try:
        return hydrate_webhook_message_event(event_id)
    except Exception as exc:
        countdown = min(10 * (2**self.request.retries), 300)
        raise self.retry(exc=exc, countdown=countdown) from exc


@shared_task(name="webhooks.dispatch_n8n_outbox_event_task")
def dispatch_n8n_outbox_event_task(outbox_id: str) -> bool:
    """Deliver one durable outbox item; retry timing lives in the database."""
    from apps.webhooks.n8n_outbox import deliver_outbox_event

    return deliver_outbox_event(outbox_id)


@shared_task(name="webhooks.poll_n8n_outbox_task")
def poll_n8n_outbox_task() -> int:
    """Dispatch a bounded due batch and expose the remaining backlog metric."""
    from django.conf import settings

    from apps.webhooks.metrics import emit_metric
    from apps.webhooks.n8n_outbox import due_outbox_ids, pending_outbox_count

    ids = due_outbox_ids(settings.N8N_BOT_OUTBOX_BATCH_SIZE)
    dispatched = 0
    for outbox_id in ids:
        try:
            dispatch_n8n_outbox_event_task.delay(outbox_id)
        except Exception as exc:
            logger.warning(
                "n8n_outbox_poll_broker_dispatch_failed",
                outbox_id=outbox_id,
                error_type=type(exc).__name__,
            )
        else:
            dispatched += 1
    emit_metric("n8n_outbox_pending_total", pending_outbox_count(), kind="gauge")
    return dispatched


@shared_task(name="webhooks.reconcile_hubspot_messages_task")
def reconcile_hubspot_messages_task() -> int:
    """Run one disabled-by-default active-thread reconciliation pass."""
    from apps.webhooks.reconciliation import reconcile_active_threads

    return reconcile_active_threads()


__all__ = [
    "dispatch_n8n_outbox_event_task",
    "hydrate_hubspot_message_event_task",
    "poll_n8n_outbox_task",
    "process_webhook_event_task",
    "reconcile_hubspot_messages_task",
]
