"""Canonical identity rules for persisted conversation instances."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.ai_agents.models import ConversationInstance


def ticket_scope_instances(ticket_id: str) -> QuerySet[ConversationInstance]:
    """Return ticket-level placeholders, never a concrete conversation thread."""
    return ConversationInstance.objects.filter(hubspot_ticket_id=str(ticket_id)).filter(
        Q(hubspot_thread_id__isnull=True) | Q(hubspot_thread_id="")
    )


def find_conversation_instance(
    *,
    thread_id: str | None = None,
    ticket_id: str | None = None,
) -> ConversationInstance | None:
    """Resolve one instance without falling from a thread into another conversation."""
    normalized_thread_id = str(thread_id or "").strip()
    if normalized_thread_id:
        return ConversationInstance.objects.filter(hubspot_thread_id=normalized_thread_id).first()

    normalized_ticket_id = str(ticket_id or "").strip()
    if normalized_ticket_id:
        return ticket_scope_instances(normalized_ticket_id).first()
    return None


def conversation_idempotency_key(
    *,
    thread_id: str | None = None,
    ticket_id: str | None = None,
    session_id: str,
) -> str:
    """Build the stable persistence key for a thread or ticket-level placeholder."""
    normalized_thread_id = str(thread_id or "").strip()
    if normalized_thread_id:
        return f"conversation:thread:{normalized_thread_id}"
    normalized_ticket_id = str(ticket_id or "").strip()
    if normalized_ticket_id:
        return f"conversation:ticket:{normalized_ticket_id}"
    return f"conversation:session:{session_id}"


__all__ = ["conversation_idempotency_key", "find_conversation_instance", "ticket_scope_instances"]
