"""Gate B (DB-02) model and constraint tests for SupportConversationCycle.

Runs on both the SQLite fast lane and the disposable PostgreSQL 16 lane; the
partial unique index is enforced by the database on both backends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.support.conversation_cycle_service import build_cycle_key
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ClosedConversation,
    ConversationReassignment,
    NewConversation,
    SupportConversationCycle,
)

pytestmark = pytest.mark.django_db

PORTAL = "12345678"
OTHER_PORTAL = "87654321"
TICKET = "9001"
ENTRY_A = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
ENTRY_B = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _cycle(
    *,
    ticket: str = TICKET,
    account: str = PORTAL,
    entered_at: datetime = ENTRY_A,
    state: str = SupportConversationCycle.State.QUEUED,
    key_suffix: str = "",
) -> SupportConversationCycle:
    return SupportConversationCycle.objects.create(
        cycle_key=build_cycle_key(
            source_system="hubspot",
            source_account_id=account,
            hubspot_ticket_id=ticket,
            entered_stage_at=entered_at,
        )
        + key_suffix,
        source_account_id=account,
        hubspot_ticket_id=ticket,
        entered_stage_at=entered_at,
        state=state,
        opened_at=entered_at,
    )


def _agent(owner_id: int = 7001) -> Agent:
    return Agent.objects.create(
        name=f"Agent {owner_id}",
        agent_email=f"agent-{owner_id}@example.test",
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
    )


class TestCycleUniqueness:
    def test_natural_key_cannot_produce_two_cycles(self) -> None:
        _cycle(entered_at=ENTRY_A)
        with pytest.raises(IntegrityError), transaction.atomic():
            _cycle(entered_at=ENTRY_A, key_suffix="-other-key")

    def test_cycle_key_is_unique(self) -> None:
        cycle = _cycle(entered_at=ENTRY_A)
        with pytest.raises(IntegrityError), transaction.atomic():
            SupportConversationCycle.objects.create(
                cycle_key=cycle.cycle_key,
                source_account_id=OTHER_PORTAL,
                hubspot_ticket_id="9999",
                entered_stage_at=ENTRY_B,
                opened_at=ENTRY_B,
            )

    def test_two_active_cycles_same_ticket_are_rejected(self) -> None:
        _cycle(entered_at=ENTRY_A, state=SupportConversationCycle.State.QUEUED)
        with pytest.raises(IntegrityError), transaction.atomic():
            _cycle(entered_at=ENTRY_B, state=SupportConversationCycle.State.ASSIGNED)

    def test_repair_required_occupies_the_active_slot(self) -> None:
        _cycle(entered_at=ENTRY_A, state=SupportConversationCycle.State.REPAIR_REQUIRED)
        with pytest.raises(IntegrityError), transaction.atomic():
            _cycle(entered_at=ENTRY_B, state=SupportConversationCycle.State.QUEUED)

    def test_multiple_terminal_cycles_same_ticket_are_accepted(self) -> None:
        _cycle(entered_at=ENTRY_A, state=SupportConversationCycle.State.CLOSED)
        _cycle(entered_at=ENTRY_B, state=SupportConversationCycle.State.CANCELLED)
        assert SupportConversationCycle.objects.filter(hubspot_ticket_id=TICKET).count() == 2

    def test_terminal_then_new_active_cycle_is_accepted(self) -> None:
        _cycle(entered_at=ENTRY_A, state=SupportConversationCycle.State.CLOSED)
        _cycle(entered_at=ENTRY_B, state=SupportConversationCycle.State.QUEUED)
        assert SupportConversationCycle.objects.count() == 2

    def test_different_accounts_do_not_collide(self) -> None:
        _cycle(entered_at=ENTRY_A, account=PORTAL)
        _cycle(entered_at=ENTRY_A, account=OTHER_PORTAL)
        assert SupportConversationCycle.objects.count() == 2


class TestProjectionCycleForeignKeys:
    def test_all_projection_fks_accept_null(self) -> None:
        agent = _agent()
        now = timezone.now()
        queue_row = NewConversation.objects.create(hubspot_ticket_id="n1", entered_queue_at=now)
        assigned = AssignedConversation.objects.create(
            hubspot_ticket_id="a1",
            hubspot_owner_id=agent.hubspot_owner_id,
            agent_name=agent.name,
            assigned_at=now,
        )
        attempt = AssignmentAttempt.objects.create(
            idempotency_key=uuid.uuid4(),
            ticket_id="t1",
            selected_agent=agent,
            eligibility_revision=1,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_reason="eligible",
            reserved_at=now,
        )
        log = AssignmentLog.objects.create(ticket_id="l1", agent_name=agent.name)
        closed = ClosedConversation.objects.create(hubspot_ticket_id="c1", closed_at=now)
        reassignment = ConversationReassignment.objects.create(hubspot_ticket_id="r1", reassigned_at=now)
        for row in (queue_row, assigned, attempt, log, closed, reassignment):
            assert row.cycle_id is None

    def test_fks_point_to_the_correct_cycle_when_filled(self) -> None:
        agent = _agent()
        now = timezone.now()
        cycle = _cycle(entered_at=ENTRY_A)
        queue_row = NewConversation.objects.create(hubspot_ticket_id=TICKET, entered_queue_at=now, cycle=cycle)
        assigned = AssignedConversation.objects.create(
            hubspot_ticket_id="a2",
            hubspot_owner_id=agent.hubspot_owner_id,
            agent_name=agent.name,
            assigned_at=now,
            cycle=cycle,
        )
        attempt = AssignmentAttempt.objects.create(
            idempotency_key=uuid.uuid4(),
            ticket_id=TICKET,
            selected_agent=agent,
            eligibility_revision=1,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_reason="eligible",
            reserved_at=now,
            cycle=cycle,
        )
        log = AssignmentLog.objects.create(ticket_id=TICKET, agent_name=agent.name, cycle=cycle)
        closed = ClosedConversation.objects.create(hubspot_ticket_id="c2", closed_at=now, cycle=cycle)
        reassignment = ConversationReassignment.objects.create(
            hubspot_ticket_id=TICKET,
            reassigned_at=now,
            cycle=cycle,
        )
        for row in (queue_row, assigned, attempt, log, closed, reassignment):
            assert row.cycle_id == cycle.pk
        assert cycle.new_conversations.count() == 1
        assert cycle.assignment_attempts.count() == 1
