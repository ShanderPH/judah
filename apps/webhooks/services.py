"""Business logic for webhook processing."""

from datetime import UTC

import structlog

from apps.webhooks.models import DeadLetterQueue, WebhookEvent

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3


def record_webhook_event(source: str, event_type: str, payload: dict) -> WebhookEvent:
    """Persist an incoming webhook event.

    Args:
        source: The originating system (hubspot, jira, etc.).
        event_type: Specific event type identifier.
        payload: The raw webhook payload.

    Returns:
        The created WebhookEvent instance.
    """
    event = WebhookEvent.objects.create(
        source=source,
        event_type=event_type,
        payload=payload,
    )
    logger.info("webhook_event_recorded", event_id=event.pk, source=source, event_type=event_type)
    return event


def process_webhook_event(event_id: int) -> bool:
    """Dispatch a recorded webhook event to the appropriate handler.

    Args:
        event_id: Primary key of the WebhookEvent to process.

    Returns:
        True if processing succeeded, False otherwise.
    """
    from datetime import datetime

    try:
        event = WebhookEvent.objects.get(pk=event_id)
    except WebhookEvent.DoesNotExist:
        logger.error("webhook_event_not_found", event_id=event_id)
        return False

    try:
        if event.source == WebhookEvent.Source.HUBSPOT:
            from apps.webhooks.handlers.hubspot_handler import handle_hubspot_event

            handle_hubspot_event(event)
        elif event.source == WebhookEvent.Source.JIRA:
            from apps.webhooks.handlers.jira_handler import handle_jira_event

            handle_jira_event(event)

        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = datetime.now(tz=UTC)
        event.save(update_fields=["status", "processed_at"])
        logger.info("webhook_event_processed", event_id=event.pk)
        return True

    except Exception as exc:
        event.retry_count += 1
        event.error_message = str(exc)

        if event.retry_count >= MAX_RETRIES:
            event.status = WebhookEvent.Status.DEAD_LETTER
            DeadLetterQueue.objects.get_or_create(
                event=event,
                defaults={"failure_reason": str(exc)},
            )
            logger.error("webhook_event_dead_letter", event_id=event.pk, error=str(exc))
        else:
            event.status = WebhookEvent.Status.FAILED
            logger.warning("webhook_event_failed", event_id=event.pk, retry=event.retry_count, error=str(exc))

        event.save(update_fields=["status", "retry_count", "error_message"])
        return False
