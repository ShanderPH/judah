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
        logger.debug("hubspot_conversation_event_recorded", event_type=event_type)
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
        logger.info(
            "hubspot_ticket_property_changed",
            ticket_id=object_id,
            property_name=property_name,
        )

        if property_name == _PROP_STAGE_NOVO:
            _handle_ticket_entered_novo(object_id, property_value, source_event_id=source_event_id)

        elif property_name == _PROP_STAGE_CLOSED:
            _handle_ticket_entered_closed(object_id, property_value, payload)

        elif property_name == _PROP_PIPELINE_STAGE:
            _handle_pipeline_stage_change(object_id, property_value, payload)

        elif property_name == _PROP_OWNER_ID:
            _handle_ticket_owner_change(object_id, property_value, payload)

        else:
            logger.info(
                "hubspot_ticket_property_change_recorded",
                ticket_id=object_id,
                property_name=property_name,
            )

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


def _handle_pipeline_stage_change(object_id: str, new_stage: str, payload: dict | None = None) -> None:
    """Handle support-stage transitions without duplicating closure effects."""
    payload = payload or {}
    new_stage = str(new_stage or "")
    support_new_stage = str(settings.HUBSPOT_SUPPORT_NEW_STAGE_ID)
    support_closed_stage = str(settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID)

    if new_stage == support_new_stage:
        entered_at_ms = payload.get("occurredAt") or payload.get("occurred_at")
        _handle_ticket_entered_novo(object_id, str(entered_at_ms) if entered_at_ms else None)
    elif new_stage == support_closed_stage:
        logger.info(
            "hubspot_ticket_pipeline_stage_fechado_logged",
            ticket_id=object_id,
            note=f"closure dispatched by {_PROP_STAGE_CLOSED} handler, not here",
        )


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


def _handle_contact_event(event_type: str, payload: dict) -> None:
    """Log contact events; they cannot represent HubSpot user availability."""
    object_id = str(payload.get("objectId", ""))
    logger.debug("hubspot_contact_event", event_type=event_type, object_id=object_id)
