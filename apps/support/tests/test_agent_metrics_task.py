"""Tests for task_aggregate_agent_metrics Celery task.

Covers:
- Upserts AgentMetrics row per active agent
- Aggregates total_chats from closed_conversations + assignment_logs
- Aggregates chats_closed from closed_conversations
- Computes avg handle time and avg wait time
- Skips agents with is_active=False
- Includes agents with is_active=None
- Idempotent: re-running updates existing rows
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.support.models import Agent, AgentMetrics, AssignmentLog, ClosedConversation
from apps.support.tasks import task_aggregate_agent_metrics


def _make_agent(
    name: str,
    owner_id: int,
    is_active: bool | None = True,
) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}@test.com",
        hubspot_owner_id=owner_id,
        status_enum="online",
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=is_active,
    )


def _make_closed(agent: Agent, handle_min: float | None = None, wait_secs: float | None = None) -> ClosedConversation:
    return ClosedConversation.objects.create(
        hubspot_ticket_id=f"T-CLOSED-{ClosedConversation.objects.count() + 1}",
        agent=agent,
        hubspot_owner_id=agent.hubspot_owner_id,
        agent_name=agent.name,
        closed_at=timezone.now(),
        total_handle_time_minutes=handle_min,
        queue_wait_seconds=wait_secs,
    )


def _make_assignment_log(agent: Agent) -> AssignmentLog:
    return AssignmentLog.objects.create(
        ticket_id=f"T-LOG-{AssignmentLog.objects.count() + 1}",
        agent=agent,
        agent_name=agent.name,
        hubspot_owner_id=agent.hubspot_owner_id,
        assignment_type="automatic",
    )


@pytest.mark.django_db
class TestTaskAggregateAgentMetrics:
    def test_creates_metrics_row_per_active_agent(self) -> None:
        agent_a = _make_agent("Alpha", 100)
        agent_b = _make_agent("Beta", 101)

        result = task_aggregate_agent_metrics()

        assert AgentMetrics.objects.filter(agent_id=agent_a.hubspot_owner_id).exists()
        assert AgentMetrics.objects.filter(agent_id=agent_b.hubspot_owner_id).exists()
        assert result["updated"] + result["skipped"] == 2

    def test_counts_closed_conversations(self) -> None:
        agent = _make_agent("Carla", 200)
        _make_closed(agent)
        _make_closed(agent)
        _make_closed(agent)

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert metrics.chats_closed == 3

    def test_total_chats_includes_assignment_logs(self) -> None:
        agent = _make_agent("Diego", 300)
        _make_closed(agent)
        _make_assignment_log(agent)
        _make_assignment_log(agent)

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert metrics.chats_closed == 1
        assert metrics.total_chats == 3

    def test_computes_average_handle_time(self) -> None:
        agent = _make_agent("Ester", 400)
        _make_closed(agent, handle_min=10.0)
        _make_closed(agent, handle_min=20.0)

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert abs(metrics.average_ticket_time_min - 15.0) < 0.01

    def test_computes_average_wait_time_in_minutes(self) -> None:
        agent = _make_agent("Fred", 500)
        _make_closed(agent, wait_secs=60.0)
        _make_closed(agent, wait_secs=120.0)

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert abs(metrics.average_response_time_min - 1.5) < 0.01

    def test_zero_metrics_when_no_data(self) -> None:
        agent = _make_agent("Grace", 600)

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert metrics.chats_closed == 0
        assert metrics.total_chats == 0
        assert metrics.average_ticket_time_min == 0.0

    def test_skips_agent_with_is_active_false(self) -> None:
        inactive = _make_agent("Inactive", 700, is_active=False)

        task_aggregate_agent_metrics()

        assert not AgentMetrics.objects.filter(agent_id=inactive.hubspot_owner_id).exists()

    def test_includes_agent_with_is_active_null(self) -> None:
        agent = _make_agent("NullActive", 800, is_active=None)
        _make_closed(agent)

        task_aggregate_agent_metrics()

        assert AgentMetrics.objects.filter(agent_id=agent.hubspot_owner_id).exists()
        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert metrics.chats_closed == 1

    def test_idempotent_reruns_update_existing_row(self) -> None:
        agent = _make_agent("Hugo", 900)
        _make_closed(agent)

        task_aggregate_agent_metrics()
        _make_closed(agent)
        _make_closed(agent)
        task_aggregate_agent_metrics()

        assert AgentMetrics.objects.filter(agent_id=agent.hubspot_owner_id).count() == 1
        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        assert metrics.chats_closed == 3

    def test_last_time_updated_is_recent(self) -> None:
        from django.utils.timezone import make_aware

        agent = _make_agent("Iris", 1000)
        before = timezone.now()

        task_aggregate_agent_metrics()

        metrics = AgentMetrics.objects.get(agent_id=agent.hubspot_owner_id)
        last_updated = metrics.last_time_updated
        if last_updated.tzinfo is None:
            last_updated = make_aware(last_updated)
        assert last_updated >= before
