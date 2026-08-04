"""Tests for one-to-many attendant history on AI conversation instances."""

from __future__ import annotations

import pytest

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.services.lifecycle import LifecycleEngine
from apps.support.conversation_attendant_service import record_instance_attendant
from apps.support.models import Agent, ConversationInstanceAttendant


def _agent(name: str, owner_id: int) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}@example.com",
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
    )


@pytest.mark.django_db
def test_instance_preserves_multiple_attendants_in_the_same_cycle() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:many-attendants",
        hubspot_thread_id="many-attendants",
        state=ConversationInstance.State.HUMAN_ASSIGNED,
    )
    ana = _agent("Ana", 101)
    bruno = _agent("Bruno", 102)

    first = record_instance_attendant(
        instance=instance,
        agent=ana,
        source=ConversationInstanceAttendant.Source.AUTOMATIC_ASSIGNMENT,
    )
    duplicate = record_instance_attendant(
        instance=instance,
        agent=ana,
        source=ConversationInstanceAttendant.Source.OWNER_CHANGE,
    )
    second = record_instance_attendant(
        instance=instance,
        agent=bruno,
        source=ConversationInstanceAttendant.Source.FORCED_REASSIGNMENT,
    )

    assert first.pk == duplicate.pk
    assert first.service_cycle_id == second.service_cycle_id
    assert instance.attendants.count() == 2
    assert set(instance.attendants.values_list("hubspot_owner_id", flat=True)) == {101, 102}


@pytest.mark.django_db
def test_same_agent_can_attend_again_after_reopening() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:returning-attendant",
        hubspot_thread_id="returning-attendant",
        state=ConversationInstance.State.HUMAN_ASSIGNED,
    )
    agent = _agent("Carla", 103)
    first = record_instance_attendant(
        instance=instance,
        agent=agent,
        source=ConversationInstanceAttendant.Source.AUTOMATIC_ASSIGNMENT,
    )
    engine = LifecycleEngine()
    engine.transition(instance, ConversationInstance.State.RESOLVED_BY_HUMAN, reason="Resolved by human.")
    engine.transition(instance, ConversationInstance.State.CLOSED, reason="Ticket closed.")
    engine.transition(
        instance,
        ConversationInstance.State.QUEUE_PENDING,
        reason="Customer reopened the ticket.",
        allow_terminal_reopen=True,
    )
    engine.transition(instance, ConversationInstance.State.HUMAN_ASSIGNED, reason="Agent assigned again.")
    second = record_instance_attendant(
        instance=instance,
        agent=agent,
        source=ConversationInstanceAttendant.Source.AUTOMATIC_ASSIGNMENT,
    )

    assert first.pk != second.pk
    assert first.service_cycle_id != second.service_cycle_id
    assert instance.attendants.filter(agent=agent).count() == 2
