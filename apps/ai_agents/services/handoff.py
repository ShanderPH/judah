"""Human handoff package builder for AI-to-support transfers."""

from __future__ import annotations

from typing import Any

from apps.ai_agents.contracts import ConversationContext, TriageDecision
from apps.ai_agents.models import ConversationInstance


def build_handoff_package(
    *,
    instance: ConversationInstance,
    reason: str,
    conversation_context: ConversationContext | None = None,
    triage_decision: TriageDecision | None = None,
    ai_summary: str = "",
    missing_data: list[str] | None = None,
) -> dict[str, Any]:
    """Build the minimum context a human agent needs after AI escalation."""
    recent_messages = []
    if conversation_context is not None:
        recent_messages = [
            {
                "direction": message.direction,
                "text": message.text,
                "created_at": message.created_at,
                "actor_id": message.actor_id,
                "message_id": message.message_id,
            }
            for message in conversation_context.recent_messages[-10:]
        ]

    triage_payload = triage_decision.model_dump(mode="json") if triage_decision is not None else None
    return {
        "conversation_instance_id": str(instance.pk),
        "state": instance.state,
        "hubspot_thread_id": instance.hubspot_thread_id,
        "hubspot_ticket_id": instance.hubspot_ticket_id,
        "hubspot_contact_id": instance.hubspot_contact_id,
        "channel": instance.channel,
        "assigned_agent_id": instance.assigned_agent_id,
        "reason": reason,
        "priority": triage_payload.get("prioridade") if triage_payload else None,
        "tags": triage_payload.get("tags", []) if triage_payload else [],
        "missing_data": missing_data or (triage_payload.get("dados_faltantes", []) if triage_payload else []),
        "triage": triage_payload,
        "ai_summary": ai_summary,
        "recent_messages": recent_messages,
        "recommended_queue": "support_n1",
    }


__all__ = ["build_handoff_package"]
