"""Business logic for webhook processing."""

import structlog

from apps.webhooks.models import DeadLetterQueue, WebhookEvent

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3


def record_webhook_event(source: str, event_type: str, payload: dict) -> WebhookEvent:
    """Persist an incoming webhook event.

    Args:
        source: The originating system (hubspot, jira, etc.) — used for routing.
        event_type: Specific event type identifier.
        payload: The raw webhook payload.

    Returns:
        The created WebhookEvent instance.
    """
    event = WebhookEvent.objects.create(
        event_type=event_type,
        event_id=str(payload.get("eventId", "") or ""),
        object_id=str(payload.get("objectId", "") or payload.get("object_id", "") or ""),
        property_name=payload.get("propertyName") or payload.get("property_name"),
        property_value=payload.get("propertyValue") or payload.get("property_value"),
        payload=payload,
    )
    logger.info("webhook_event_recorded", event_id=event.pk, source=source, event_type=event_type)
    return event


def process_webhook_event(event_id) -> bool:
    """Dispatch a recorded webhook event to the appropriate handler.

    Routes by event_type prefix:
      - ``ticket.*`` / ``contact.*`` / ``deal.*`` / ``company.*``  → HubSpot handler
      - ``conversation.*``  → HubSpot Conversations handler (legacy)

    Args:
        event_id: Primary key of the WebhookEvent to process.

    Returns:
        True if processing succeeded, False otherwise.
    """
    from django.utils import timezone

    try:
        event = WebhookEvent.objects.get(pk=event_id)
    except WebhookEvent.DoesNotExist:
        logger.error("webhook_event_not_found", event_id=event_id)
        return False

    try:
        et = (event.event_type or "").lower()

        # HubSpot CRM + Conversations events
        if et.startswith(("ticket.", "contact.", "deal.", "company.", "conversation.")):
            from apps.webhooks.handlers.hubspot_handler import handle_hubspot_event

            handle_hubspot_event(event)

        # Unknown event type - mark as processed but log for visibility
        elif et == "unknown":
            logger.warning(
                "webhook_event_unknown_type",
                event_id=event.pk,
                payload_keys=list(event.payload.keys()) if event.payload else [],
            )

        # Fallback: try Jira handler for other event types
        else:
            try:
                from apps.webhooks.handlers.jira_handler import handle_jira_event

                handle_jira_event(event)
            except ImportError:
                logger.debug("webhook_event_no_handler", event_type=event.event_type)

        event.processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["processed", "processed_at"])
        logger.info("webhook_event_processed", event_id=event.pk)
        return True

    except Exception as exc:
        event.retry_count += 1
        event.error_message = str(exc)

        if event.retry_count >= MAX_RETRIES:
            DeadLetterQueue.objects.get_or_create(
                event=event,
                defaults={"failure_reason": str(exc)},
            )
            logger.error("webhook_event_dead_letter", event_id=event.pk, error=str(exc))
        else:
            logger.warning("webhook_event_failed", event_id=event.pk, retry=event.retry_count, error=str(exc))

        event.save(update_fields=["retry_count", "error_message"])
        return False
