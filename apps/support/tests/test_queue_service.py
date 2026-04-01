"""Unit tests for the auto-assignment queue service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.utils import timezone

from apps.support.models import Agent, AssignmentLog, NewConversation
from apps.support.queue_service import (
    decrement_agent_chat_count,
    get_eligible_agents,
    get_last_assigned_owner_id,
    get_queue_status,
    increment_agent_chat_count,
    select_next_agent,
)


def _make_agent(
    name: str,
    owner_id: int,
    status: str = "online",
    chats: int = 0,
    max_chats: int = 5,
    auto_assign: bool = True,
    last_assignment_at: datetime | None = None,
) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower().replace(' ', '.')}@test.com",
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=chats,
        max_simultaneous_chats=max_chats,
        auto_assign_enabled=auto_assign,
        is_active=True,
        last_assignment_at=last_assignment_at,
    )


@pytest.mark.django_db
class TestGetEligibleAgents:
    def test_returns_online_agents_only(self) -> None:
        _make_agent("Online", 1, status="online")
        _make_agent("Away", 2, status="away")
        _make_agent("Offline", 3, status="offline")

        eligible = get_eligible_agents()

        assert len(eligible) == 1
        assert eligible[0].name == "Online"

    def test_excludes_agents_at_capacity(self) -> None:
        _make_agent("Full", 1, chats=5, max_chats=5)
        _make_agent("Available", 2, chats=2, max_chats=5)

        eligible = get_eligible_agents()

        assert len(eligible) == 1
        assert eligible[0].name == "Available"

    def test_excludes_auto_assign_disabled(self) -> None:
        _make_agent("AutoOff", 1, auto_assign=False)
        _make_agent("AutoOn", 2, auto_assign=True)

        eligible = get_eligible_agents()

        assert len(eligible) == 1
        assert eligible[0].name == "AutoOn"

    def test_excludes_inactive_agents(self) -> None:
        agent = _make_agent("Inactive", 1)
        agent.is_active = False
        agent.save()
        _make_agent("Active", 2)

        eligible = get_eligible_agents()

        assert len(eligible) == 1
        assert eligible[0].name == "Active"

    def test_empty_when_no_online_agents(self) -> None:
        _make_agent("Away", 1, status="away")
        assert get_eligible_agents() == []


@pytest.mark.django_db
class TestSelectNextAgent:
    def test_returns_none_when_no_eligible(self) -> None:
        assert select_next_agent() is None

    def test_selects_agent_with_null_last_assignment_first(self) -> None:
        _make_agent(
            "OldAgent",
            1,
            last_assignment_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        _make_agent("NeverAssigned", 2, last_assignment_at=None)

        selected = select_next_agent()

        assert selected is not None
        assert selected.name == "NeverAssigned"

    def test_rule2_excludes_last_assigned_agent(self) -> None:
        a1 = _make_agent("AgentA", 101)
        _make_agent("AgentB", 102)

        selected = select_next_agent(last_assigned_hubspot_owner_id=101)

        assert selected is not None
        assert selected.pk != a1.pk
        assert selected.name == "AgentB"

    def test_rule2_fallback_when_only_one_agent(self) -> None:
        agent = _make_agent("Solo", 1)

        selected = select_next_agent(last_assigned_hubspot_owner_id=1)

        assert selected is not None
        assert selected.pk == agent.pk

    def test_prefers_agent_with_fewer_chats(self) -> None:
        old = datetime(2025, 6, 1, tzinfo=UTC)
        _make_agent("BusyAgent", 1, chats=3, last_assignment_at=old)
        _make_agent("FreeAgent", 2, chats=0, last_assignment_at=old)

        selected = select_next_agent()

        assert selected is not None
        assert selected.name == "FreeAgent"


@pytest.mark.django_db
class TestIncrementDecrement:
    def test_increment_increases_chat_count(self) -> None:
        agent = _make_agent("Agent", 1, chats=2)
        increment_agent_chat_count(agent)
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 3

    def test_decrement_decreases_chat_count(self) -> None:
        agent = _make_agent("Agent", 1, chats=3)
        decrement_agent_chat_count(agent)
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 2

    def test_decrement_does_not_go_below_zero(self) -> None:
        agent = _make_agent("Agent", 1, chats=0)
        decrement_agent_chat_count(agent)
        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 0


@pytest.mark.django_db
class TestGetLastAssignedOwnerId:
    def test_returns_none_when_no_logs(self) -> None:
        assert get_last_assigned_owner_id() is None

    def test_returns_most_recent_auto_assignment(self) -> None:
        AssignmentLog.objects.create(
            ticket_id="T001",
            agent_name="Agent A",
            hubspot_owner_id=111,
            assignment_type="auto",
            assigned_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        )
        AssignmentLog.objects.create(
            ticket_id="T002",
            agent_name="Agent B",
            hubspot_owner_id=222,
            assignment_type="auto",
            assigned_at=datetime(2026, 3, 1, 11, 0, tzinfo=UTC),
        )

        result = get_last_assigned_owner_id()

        assert result == 222

    def test_ignores_manual_assignments(self) -> None:
        AssignmentLog.objects.create(
            ticket_id="T001",
            agent_name="Agent A",
            hubspot_owner_id=111,
            assignment_type="manual",
            assigned_at=timezone.now(),
        )

        assert get_last_assigned_owner_id() is None


@pytest.mark.django_db
class TestGetQueueStatus:
    def test_returns_correct_counts(self) -> None:
        _make_agent("Online1", 1)
        _make_agent("Online2", 2)
        _make_agent("Away1", 3, status="away")
        NewConversation.objects.create(
            hubspot_ticket_id="T001",
            pipeline_id="636459134",
            entered_queue_at=timezone.now(),
            is_pending=True,
        )

        status = get_queue_status()

        assert status["online_agents"] == 2
        assert status["eligible_agents"] == 2
        assert status["pending_queue_depth"] == 1
        assert len(status["agents"]) == 2
