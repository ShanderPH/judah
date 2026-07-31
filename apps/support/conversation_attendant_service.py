"""Persist the human agents who attended each conversation service cycle."""

from __future__ import annotations

from django.db import transaction

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.instance_identity import canonical_thread_instances, ticket_scope_instances
from apps.ai_agents.services.service_cycles import ensure_current_service_cycle
from apps.support.models import Agent, ConversationInstanceAttendant

_HUMAN_STATES = {
    ConversationInstance.State.HUMAN_HANDOFF_REQUESTED,
    ConversationInstance.State.QUEUE_PENDING,
    ConversationInstance.State.HUMAN_ASSIGNED,
    ConversationInstance.State.HUMAN_IN_PROGRESS,
    ConversationInstance.State.RESOLVED_BY_HUMAN,
}


@transaction.atomic
def record_instance_attendant(
    *,
    instance: ConversationInstance,
    agent: Agent,
    source: str,
    metadata: dict[str, object] | None = None,
) -> ConversationInstanceAttendant:
    """Record one agent once per service cycle without losing prior history."""
    locked = ConversationInstance.objects.select_for_update().get(pk=instance.pk)
    cycle = ensure_current_service_cycle(locked)
    attendant, created = ConversationInstanceAttendant.objects.get_or_create(
        service_cycle=cycle,
        agent=agent,
        defaults={
            "instance": locked,
            "hubspot_owner_id": agent.hubspot_owner_id,
            "agent_name": agent.name,
            "source": source,
            "metadata": metadata or {},
        },
    )
    if not created:
        update_fields = ["last_seen_at"]
        if attendant.hubspot_owner_id != agent.hubspot_owner_id:
            attendant.hubspot_owner_id = agent.hubspot_owner_id
            update_fields.append("hubspot_owner_id")
        if attendant.agent_name != agent.name:
            attendant.agent_name = agent.name
            update_fields.append("agent_name")
        attendant.save(update_fields=update_fields)
    return attendant


def record_ticket_attendant(
    *,
    ticket_id: str,
    agent: Agent,
    source: str,
    metadata: dict[str, object] | None = None,
) -> list[ConversationInstanceAttendant]:
    """Record an agent on every active human lifecycle instance for a ticket."""
    normalized_ticket_id = str(ticket_id).strip()
    if not normalized_ticket_id:
        return []
    instances = list(
        ConversationInstance.objects.filter(
            hubspot_ticket_id=normalized_ticket_id,
            state__in=_HUMAN_STATES,
        ).order_by("created_at", "pk")
    )
    if not instances:
        placeholders = list(ticket_scope_instances(normalized_ticket_id).order_by("-last_activity_at")[:1])
        canonicals = list(canonical_thread_instances(normalized_ticket_id).order_by("-last_activity_at")[:1])
        instances = placeholders or canonicals
    return [
        record_instance_attendant(
            instance=instance,
            agent=agent,
            source=source,
            metadata=metadata,
        )
        for instance in instances
    ]


__all__ = ["record_instance_attendant", "record_ticket_attendant"]
