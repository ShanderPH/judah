"""Handler for HubSpot webhook events.

All event processing is dispatched asynchronously via Celery tasks.
The webhook endpoint returns 202 immediately — no blocking I/O occurs
in the request thread beyond the initial event recording.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction

logger = structlog.get_logger(__name__)

# HubSpot property names that trigger auto-assignment logic
_STAGE_NOVO_ID = settings.HUBSPOT_SUPPORT_NEW_STAGE_ID
_STAGE_FECHADO_ID = settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID
_PROP_STAGE_NOVO = f"hs_v2_date_entered_{_STAGE_NOVO_ID}"
_PROP_STAGE_CLOSED = f"hs_v2_date_entered_{_STAGE_FECHADO_ID}"
_PROP_PIPELINE_STAGE = "hs_pipeline_stage"
_PROP_OWNER_ID = "hubspot_owner_id"  # Ticket owner (agent) assignment


def handle_hubspot_event(event) -> None:
    """Route and process a HubSpot webhook event.

    Args:
        event: WebhookEvent instance with source=hubspot.
    """
    event_type: str = event.event_type
    payload: dict = event.payload
    et_lower = event_type.lower()

    logger.info("hubspot_event_received", event_type=event_type, event_id=event.pk)

    if et_lower.startswith("ticket."):
        provider_event_id = getattr(event, "event_id", "")
        _handle_ticket_event(event_type, payload, source_event_id=str(provider_event_id or event.pk))
    elif et_lower.startswith("contact."):
        _handle_contact_event(event_type, payload)
    elif et_lower.startswith("conversation."):
        _handle_conversation_event(event_type, payload)
    elif et_lower.startswith(("deal.", "company.")):
        logger.debug("hubspot_crm_event_logged", event_type=event_type, object_id=payload.get("objectId"))
    else:
        logger.debug("hubspot_event_unhandled", event_type=event_type)


def _handle_ticket_event(event_type: str, payload: dict, *, source_event_id: str = "") -> None:
    """Process ticket-related HubSpot events."""
    object_id = str(payload.get("objectId", ""))
    if not object_id:
        return

    property_name = payload.get("propertyName", "")
    property_value = payload.get("propertyValue", "")

    if event_type == "ticket.propertyChange":
        if property_name == _PROP_STAGE_NOVO:
            _handle_ticket_entered_novo(object_id, property_value, source_event_id=source_event_id)

        elif property_name == _PROP_STAGE_CLOSED:
            _handle_ticket_entered_closed(object_id, property_value, payload)

        elif property_name == _PROP_PIPELINE_STAGE:
            _handle_pipeline_stage_change(object_id, property_value)

        elif property_name == _PROP_OWNER_ID:
            _handle_ticket_owner_change(object_id, property_value, payload)

    elif event_type in ("ticket.creation", "ticket.created"):
        logger.debug("hubspot_ticket_created_event", ticket_id=object_id)
    else:
        logger.debug("hubspot_ticket_event_unhandled", event_type=event_type, ticket_id=object_id)


def _handle_ticket_entered_novo(
    hubspot_ticket_id: str,
    entered_at_ms: str | None,
    *,
    source_event_id: str = "",
) -> None:
    """Dispatch auto-assignment via Matchmaker when a ticket enters NOVO stage.

    Non-blocking — dispatches a Celery task and returns immediately.
    """
    from apps.support.availability_runtime import log_runtime_rejection, may_ingest_queue

    if not may_ingest_queue():
        log_runtime_rejection("hubspot_ticket_entered_novo")
        return

    logger.info("hubspot_ticket_entered_novo", ticket_id=hubspot_ticket_id, entered_at_ms=entered_at_ms)

    from apps.support.tasks import task_matchmaker_assign_single

    transaction.on_commit(
        lambda: task_matchmaker_assign_single.delay(hubspot_ticket_id, entered_at_ms, source_event_id)
    )


def _handle_ticket_entered_closed(hubspot_ticket_id: str, closed_at_ms: str | None, payload: dict) -> None:
    """Dispatch ticket closure processing via Celery.

    Non-blocking — dispatches a Celery task and returns immediately.
    """
    logger.info("hubspot_ticket_entered_closed", ticket_id=hubspot_ticket_id, closed_at_ms=closed_at_ms)

    from apps.support.tasks import task_handle_ticket_closed

    # Extract owner_id — avoid using sourceId as fallback since it may contain
    # non-numeric values like "StageCalculatedPropertiesRollup"
    owner_id = payload.get("hubspot_owner_id") or ""
    owner_str = str(owner_id).strip() if owner_id else None

    # Validate that it looks numeric before passing downstream
    if owner_str:
        # Handle "userId:12345" format from HubSpot
        parsed = owner_str.rsplit(":", 1)[-1] if ":" in owner_str else owner_str
        try:
            int(parsed)
        except (ValueError, TypeError):  # fmt: skip  # keep parenthesized form for py<3.14 compat
            logger.debug(
                "hubspot_ticket_closed_invalid_owner_id",
                ticket_id=hubspot_ticket_id,
                raw_owner_id=owner_id,
            )
            owner_str = None

    task_handle_ticket_closed.delay(hubspot_ticket_id, closed_at_ms, owner_str)


def _handle_pipeline_stage_change(object_id: str, new_stage: str) -> None:
    """Handle pipeline stage transitions.

    When a ticket moves to the configured FECHADO stage, this event is logged for
    observability only. The actual closure flow is triggered exclusively by the
    configured closed-stage property change event (``_PROP_STAGE_CLOSED``)
    to avoid dispatching duplicate ``task_handle_ticket_closed`` tasks.

    Dispatching closure from both ``hs_pipeline_stage`` and
    the closed-stage timestamp property would cause double decrements of
    ``current_simultaneous_chats`` even though ``handle_ticket_closed`` now
    holds a Redis dedup lock — the lock prevents re-entry within 60 s, but
    two rapid concurrent dispatches (one per webhook property) could both
    reach the cache.add() check before either has committed.
    """
    if new_stage == _STAGE_FECHADO_ID:
        # Log for observability — closure is handled by _PROP_STAGE_CLOSED handler.
        logger.info(
            "hubspot_ticket_pipeline_stage_fechado_logged",
            ticket_id=object_id,
            note=f"closure dispatched by {_PROP_STAGE_CLOSED} handler, not here",
        )
        return

    from apps.support.models import Ticket

    try:
        ticket = Ticket.objects.get(ticket_id=object_id)
        ticket.status = "RESOLVED"
        ticket.save(update_fields=["status", "updated_at"])
        logger.info("ticket_resolved_via_hubspot", ticket_id=ticket.pk)
    except Ticket.DoesNotExist:
        logger.debug("hubspot_ticket_not_synced_locally", hubspot_id=object_id)


def _handle_ticket_owner_change(
    hubspot_ticket_id: str,
    new_owner_id: str | None,
    payload: dict,
) -> None:
    """Dispatch ticket owner reassignment via Celery.

    Non-blocking — dispatches a Celery task and returns immediately.
    """
    logger.info(
        "hubspot_ticket_owner_change",
        ticket_id=hubspot_ticket_id,
        new_owner_id=new_owner_id,
    )

    from apps.support.tasks import task_handle_owner_change

    task_handle_owner_change.delay(hubspot_ticket_id, new_owner_id, payload)


def _handle_conversation_event(event_type: str, payload: dict) -> None:
    """Process HubSpot Conversations events (legacy).

    These events come from the HubSpot Conversations API and include:
      - conversation.creation
      - conversation.deletion
      - conversation.privacyDeletion
      - conversation.propertyChange
      - conversation.newMessage

    ``conversation.newMessage`` can trigger the AI Supervisor when AI routing
    and the Salomao v1 adapter are enabled. The task re-fetches the thread and
    skips non-incoming messages, protecting against loops caused by Judah's own
    outgoing replies.
    """
    object_id = str(payload.get("objectId", ""))
    logger.debug(
        "hubspot_conversation_event",
        event_type=event_type,
        object_id=object_id,
        message_id=payload.get("messageId"),
    )

    if event_type != "conversation.newMessage" or not object_id:
        return

    direction = str(payload.get("direction") or payload.get("messageDirection") or "").upper()
    if direction and direction != "INCOMING":
        logger.debug("hubspot_conversation_outgoing_skipped", object_id=object_id, direction=direction)
        return

    from apps.ai_agents.services.channel_capabilities import can_send_automated_reply, normalize_channel

    channel = normalize_channel(
        payload.get("channel")
        or payload.get("channelType")
        or payload.get("messageType")
        or payload.get("source")
        or payload.get("sourceType")
    )
    if not can_send_automated_reply(channel):
        logger.info("hubspot_conversation_auto_reply_unsupported", object_id=object_id, channel=channel)
        return

    from django.conf import settings

    if not getattr(settings, "AI_ROUTING_ENABLED", False) or not getattr(settings, "SALOMAO_V1_BASE_URL", ""):
        logger.debug("hubspot_conversation_ai_routing_disabled", object_id=object_id)
        return

    from apps.ai_agents.tasks import run_salomao_v1_thread_pipeline_task

    thread_id = (
        payload.get("threadId")
        or payload.get("conversationThreadId")
        or payload.get("conversationsThreadId")
        or object_id
    )

    run_salomao_v1_thread_pipeline_task.delay(str(thread_id))
    logger.info("hubspot_conversation_supervisor_dispatched", thread_id=str(thread_id), object_id=object_id)


def _handle_contact_event(event_type: str, payload: dict) -> None:
    """Log contact events; they cannot represent HubSpot user availability."""
    object_id = str(payload.get("objectId", ""))
    logger.debug("hubspot_contact_event", event_type=event_type, object_id=object_id)
