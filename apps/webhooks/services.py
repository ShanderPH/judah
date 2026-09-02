"""Business logic for webhook processing."""

import structlog

from apps.webhooks.models import DeadLetterQueue, WebhookEvent
from common.idempotency import canonical_event_key

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
    provider_event_id = str(payload.get("eventId", "") or "")
    defaults = {
        "object_id": str(payload.get("objectId", "") or payload.get("object_id", "") or ""),
        "property_name": payload.get("propertyName") or payload.get("property_name"),
        "property_value": payload.get("propertyValue") or payload.get("property_value"),
        "payload": payload,
    }
    deduplication_key = canonical_event_key(
        source=source,
        event_type=event_type,
        payload=payload,
    )
    event, created = WebhookEvent.objects.get_or_create(
        deduplication_key=deduplication_key,
        defaults={
            "event_type": event_type,
            "event_id": provider_event_id,
            **defaults,
        },
    )
    logger.info(
        "webhook_event_recorded",
        event_id=event.pk,
        provider_event_id=provider_event_id or None,
        source=source,
        event_type=event_type,
        created=created,
    )
    return event


def _dispatch_hubspot_lifecycle(event: WebhookEvent, lifecycle) -> None:
    """Dispatch exactly one executable path from the deterministic route."""
    from apps.webhooks.handlers.hubspot_handler import handle_hubspot_event

    decision = lifecycle.decision
    route = decision.route

    if route in {"AUTO_ASSIGNMENT", "CLOSE"}:
        handle_hubspot_event(event)
        return

    # Operational HubSpot events outside the conversation workflow still use
    # their focused deterministic handlers (owner/status changes, etc.).
    if route == "IGNORE":
        handle_hubspot_event(event)


def process_webhook_event(event_id) -> bool:
    """Dispatch a recorded webhook event to the appropriate handler.

    Routes by event_type prefix:
      - ``ticket.*`` / ``contact.*`` / ``deal.*`` / ``company.*``  → HubSpot handler
      - ``conversation.*``  -> durable lifecycle ingestion without bot dispatch

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

    if event.processed:
        logger.info("webhook_event_already_processed", event_id=event.pk)
        return True

    lifecycle = None
    try:
        et = (event.event_type or "").lower()

        # HubSpot CRM + Conversations events
        if et.startswith(("ticket.", "contact.", "deal.", "company.", "conversation.")):
            from apps.ai_agents.services.lifecycle import is_lifecycle_schema_ready, record_lifecycle_for_webhook_event
            from apps.webhooks.handlers.hubspot_handler import handle_hubspot_event

            if is_lifecycle_schema_ready():
                try:
                    lifecycle = record_lifecycle_for_webhook_event(event)
                except Exception as exc:
                    lifecycle = None
                    logger.warning(
                        "webhook_event_lifecycle_record_failed",
                        event_id=event.pk,
                        event_type=event.event_type,
                        object_id=event.object_id or None,
                        ticket_id=event.object_id if et.startswith("ticket.") else None,
                        property_name=event.property_name,
                        error_type=type(exc).__name__,
                        lifecycle_recorded=False,
                        deterministic_handler_continues=True,
                        action="continue_without_lifecycle_projection",
                    )
                    # Lifecycle observability must never suppress the
                    # deterministic support webhook handler.
                    handle_hubspot_event(event)
                else:
                    logger.info(
                        "webhook_event_lifecycle_recorded",
                        event_id=event.pk,
                        conversation_instance_id=str(lifecycle.instance.pk),
                        conversation_state=lifecycle.instance.state,
                        route=lifecycle.decision.route,
                        event_created=lifecycle.event_created,
                        stale_event=lifecycle.stale_event,
                    )
                    process_stale_occurrence = (
                        lifecycle.stale_event
                        and lifecycle.effect_policy.value == "process_idempotent_occurrence"
                        and lifecycle.event_created
                    )
                    if lifecycle.stale_event and not process_stale_occurrence:
                        logger.warning(
                            "webhook_event_stale_effects_skipped",
                            event_id=event.pk,
                            conversation_event_id=str(lifecycle.event.pk),
                            occurred_at=lifecycle.event.occurred_at,
                            projection_skipped=True,
                            effect_policy=lifecycle.effect_policy.value,
                            effect_outcome="suppressed",
                            action="preserve_newer_provider_state",
                        )
                    elif (
                        process_stale_occurrence
                        or lifecycle.event_created
                        or lifecycle.event.processing_status
                        in {
                            lifecycle.event.ProcessingStatus.PENDING,
                            lifecycle.event.ProcessingStatus.FAILED,
                        }
                    ):
                        if process_stale_occurrence:
                            logger.warning(
                                "webhook_event_stale_occurrence_revalidated",
                                event_id=event.pk,
                                conversation_event_id=str(lifecycle.event.pk),
                                projection_skipped=True,
                                effect_policy=lifecycle.effect_policy.value,
                                effect_outcome="dispatched_for_provider_revalidation",
                            )
                        _dispatch_hubspot_lifecycle(event, lifecycle)
                    else:
                        logger.info(
                            "webhook_event_duplicate_effects_skipped",
                            event_id=event.pk,
                            conversation_event_id=str(lifecycle.event.pk),
                        )
            else:
                logger.info(
                    "webhook_event_lifecycle_schema_missing",
                    event_id=event.pk,
                    event_type=event.event_type,
                )
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
        if lifecycle is not None:
            from apps.ai_agents.services.lifecycle import LifecycleEngine

            LifecycleEngine().mark_event_processed(lifecycle.event)
        logger.info(
            "webhook_event_processed",
            event_id=event.pk,
            event_type=event.event_type,
            object_id=event.object_id or None,
            lifecycle_recorded=lifecycle is not None,
            outcome="processed",
        )
        return True

    except Exception as exc:
        if lifecycle is not None:
            from apps.ai_agents.services.lifecycle import LifecycleEngine

            LifecycleEngine().mark_event_failed(lifecycle.event, exc)
        event.retry_count += 1
        event.error_message = str(exc)

        if event.retry_count >= MAX_RETRIES:
            DeadLetterQueue.objects.get_or_create(
                event=event,
                defaults={"failure_reason": str(exc)},
            )
            logger.error(
                "webhook_event_dead_letter",
                event_id=event.pk,
                error_type=type(exc).__name__,
            )
        else:
            logger.warning(
                "webhook_event_failed",
                event_id=event.pk,
                retry=event.retry_count,
                error_type=type(exc).__name__,
            )

        event.save(update_fields=["retry_count", "error_message"])
        return False
