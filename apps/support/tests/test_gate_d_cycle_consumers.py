"""Gate D coverage for cycle closure, stale owners, and isolated repair."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.support.auto_assign_service import handle_ticket_closed
from apps.support.durable_assignment_service import repair_assignment_attempts
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    ClosedConversation,
    SupportConversationCycle,
)
from apps.support.tasks import _do_handle_owner_change


def _agent(owner_id: int) -> Agent:
    return Agent.objects.create(
        name=f"Agent {owner_id}",
        agent_email=f"agent-{owner_id}@example.test",
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        current_simultaneous_chats=1,
        max_simultaneous_chats=5,
    )


def _cycle(ticket_id: str, entered_at) -> SupportConversationCycle:
    return SupportConversationCycle.objects.create(
        cycle_key=f"v1:test:{ticket_id}:{entered_at.timestamp()}",
        source_account_id="portal-1",
        hubspot_ticket_id=ticket_id,
        entered_stage_at=entered_at,
        opened_at=entered_at,
        state=SupportConversationCycle.State.ASSIGNED,
    )


def _assigned(ticket_id: str, cycle: SupportConversationCycle, agent: Agent) -> AssignedConversation:
    return AssignedConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        cycle=cycle,
        agent=agent,
        hubspot_owner_id=agent.hubspot_owner_id,
        agent_name=agent.name,
        assigned_at=cycle.entered_stage_at,
    )


@pytest.mark.django_db
def test_two_reopened_cycles_preserve_two_closures() -> None:
    ticket_id = "reopened-1"
    agent = _agent(7001)
    first_entered = timezone.now() - timedelta(hours=2)
    first = _cycle(ticket_id, first_entered)
    _assigned(ticket_id, first, agent)
    handle_ticket_closed(ticket_id, str(int((first_entered + timedelta(hours=1)).timestamp() * 1000)))

    second_entered = timezone.now() - timedelta(minutes=30)
    second = _cycle(ticket_id, second_entered)
    _assigned(ticket_id, second, agent)
    handle_ticket_closed(ticket_id, str(int((second_entered + timedelta(minutes=15)).timestamp() * 1000)))

    assert ClosedConversation.objects.filter(hubspot_ticket_id=ticket_id).count() == 2
    assert set(ClosedConversation.objects.filter(hubspot_ticket_id=ticket_id).values_list("cycle_id", flat=True)) == {
        first.pk,
        second.pk,
    }


@pytest.mark.django_db
def test_old_owner_event_does_not_mutate_current_cycle() -> None:
    old_agent = _agent(7101)
    current_agent = _agent(7102)
    target = _agent(7103)
    cycle = _cycle("owner-stale", timezone.now() - timedelta(minutes=10))
    assigned = _assigned("owner-stale", cycle, current_agent)

    _do_handle_owner_change("owner-stale", old_agent.hubspot_owner_id, target.hubspot_owner_id)

    assigned.refresh_from_db()
    assert assigned.agent == current_agent
    assert assigned.assignment_count == 1


@pytest.mark.django_db
def test_poisoned_repair_item_does_not_block_batch() -> None:
    agent = _agent(7201)
    now = timezone.now()
    attempts = [
        AssignmentAttempt.objects.create(
            idempotency_key=uuid.uuid4(),
            ticket_id=f"repair-{index}",
            selected_agent=agent,
            eligibility_revision=0,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_reason="test",
            state=AssignmentAttempt.State.REPAIR_REQUIRED,
            reserved_at=now,
        )
        for index in range(2)
    ]
    with patch(
        "apps.support.durable_assignment_service.reconcile_ambiguous_attempt",
        side_effect=[RuntimeError("poison"), "repair_required"],
    ):
        counts = repair_assignment_attempts(limit=10)

    assert counts["failed_unexpected"] == 1
    assert counts["repair_required"] == 1
    assert counts["scanned"] == 2
    attempts[0].refresh_from_db()
    assert attempts[0].last_error_code == "RuntimeError"
