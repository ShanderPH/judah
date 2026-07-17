"""Extended coverage for support Celery task orchestration."""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.support.models import (
    Agent,
    AgentStatusHistory,
    AssignedConversation,
    ConversationReassignment,
    NewConversation,
    QueuePerformanceMetrics,
)
from apps.support.tasks import (
    _do_handle_owner_change,
    task_aggregate_queue_metrics,
    task_handle_availability_change,
    task_handle_owner_change,
    task_handle_ticket_closed,
    task_matchmaker_assign_single,
    task_matchmaker_drain_queue,
    task_reconcile_agent_counts,
    task_sat_heartbeat,
    task_sat_reset_daily_counters,
    task_sync_hubspot_team_members,
    task_sync_novo_stage_tickets,
)


def test_sat_task_wrappers() -> None:
    with patch("apps.support.sat_service.sat_heartbeat", return_value={"checked": 2}):
        assert task_sat_heartbeat.run() == {"checked": 2}
    with patch("apps.support.sat_service.sat_reset_daily_counters", return_value={"reset": 2}):
        assert task_sat_reset_daily_counters.run() == {"reset": 2}


def test_matchmaker_assign_task_paths() -> None:
    cache = Mock()
    cache.add.return_value = False
    with patch("django.core.cache.cache", cache):
        assert task_matchmaker_assign_single.run("ticket-1") is False

    cache.add.return_value = True
    with (
        patch("django.core.cache.cache", cache),
        patch("apps.support.matchmaker_service.enqueue_new_ticket", return_value=None),
    ):
        assert task_matchmaker_assign_single.run("ticket-1") is False

    with (
        patch("django.core.cache.cache", cache),
        patch("apps.support.matchmaker_service.enqueue_new_ticket", return_value=SimpleNamespace()),
        patch(
            "apps.support.matchmaker_service.matchmaker_assign_next",
            return_value=SimpleNamespace(value="assigned"),
        ),
    ):
        assert task_matchmaker_assign_single.run("ticket-1") is True

    with (
        patch("django.core.cache.cache", cache),
        patch("apps.support.matchmaker_service.enqueue_new_ticket", side_effect=RuntimeError("db")),
        patch.object(task_matchmaker_assign_single, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        task_matchmaker_assign_single.run("ticket-1")


def test_matchmaker_drain_task_paths() -> None:
    with patch("apps.support.agent_sync_service.is_business_hours", return_value=False):
        assert task_matchmaker_drain_queue.run() == {"skipped_off_hours": True}

    cache = Mock()
    cache.add.return_value = False
    with (
        patch("apps.support.agent_sync_service.is_business_hours", return_value=True),
        patch("django.core.cache.cache", cache),
    ):
        assert task_matchmaker_drain_queue.run() == {"skipped_locked": True}

    cache.add.return_value = True
    with (
        patch("apps.support.agent_sync_service.is_business_hours", return_value=True),
        patch("django.core.cache.cache", cache),
        patch("apps.support.matchmaker_service.matchmaker_drain_queue", return_value={"assigned": 2}),
    ):
        assert task_matchmaker_drain_queue.run() == {"assigned": 2}
    cache.delete.assert_called()


def test_ticket_closed_and_owner_change_task_retries() -> None:
    with patch("apps.support.auto_assign_service.handle_ticket_closed") as closed:
        task_handle_ticket_closed.run("ticket", "123", "10")
    closed.assert_called_once_with("ticket", "123", "10")

    with (
        patch("apps.support.auto_assign_service.handle_ticket_closed", side_effect=RuntimeError("db")),
        patch.object(task_handle_ticket_closed, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        task_handle_ticket_closed.run("ticket")

    with patch("apps.support.auto_assign_service._safe_parse_owner_id", return_value=None):
        assert task_handle_owner_change.run("ticket", "10", {}) is None
    with patch("apps.support.auto_assign_service._safe_parse_owner_id", side_effect=[10, 10]):
        assert task_handle_owner_change.run("ticket", "10", {"previousValue": "10"}) is None


@pytest.mark.django_db
def test_owner_change_updates_assignment_and_audit() -> None:
    previous = Agent.objects.create(name="Ana", agent_email="ana@example.com", hubspot_owner_id=10)
    target = Agent.objects.create(name="Bia", agent_email="bia@example.com", hubspot_owner_id=11)
    assigned = AssignedConversation.objects.create(
        hubspot_ticket_id="ticket-owner",
        agent=previous,
        hubspot_owner_id=10,
        agent_name="Ana",
        assigned_at=timezone.now() - timedelta(minutes=5),
    )
    with (
        patch("apps.support.queue_service.decrement_agent_chat_count") as decrement,
        patch("apps.support.queue_service.increment_agent_chat_count") as increment,
    ):
        _do_handle_owner_change("ticket-owner", 10, 11)

    assigned.refresh_from_db()
    assert assigned.agent == target
    assert assigned.assignment_count == 2
    decrement.assert_called_once_with(previous)
    increment.assert_called_once_with(target)
    audit = ConversationReassignment.objects.get(hubspot_ticket_id="ticket-owner")
    assert audit.time_with_previous_agent_seconds is not None


def test_owner_change_lock_and_retry_paths() -> None:
    cache = Mock()
    cache.add.return_value = False
    with (
        patch("django.core.cache.cache", cache),
        patch("apps.support.auto_assign_service._safe_parse_owner_id", side_effect=[10, 11]),
        patch("apps.support.tasks._do_handle_owner_change") as process,
    ):
        task_handle_owner_change.run("ticket", "11", {"previousValue": "10"})
    process.assert_not_called()

    cache.add.return_value = True
    with (
        patch("django.core.cache.cache", cache),
        patch("apps.support.auto_assign_service._safe_parse_owner_id", side_effect=RuntimeError("bad")),
        patch.object(task_handle_owner_change, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        task_handle_owner_change.run("ticket", "11", {"previousValue": "10"})


@pytest.mark.django_db
def test_availability_change_updates_agent_and_dispatches() -> None:
    agent = Agent.objects.create(
        name="Ana",
        agent_email="ana@example.com",
        hubspot_owner_id=10,
        status_enum=Agent.StatusEnum.AWAY,
    )
    with (
        patch("apps.support.sat_service.sat_accumulate_time") as accumulate,
        patch("apps.support.tasks.task_matchmaker_drain_queue.delay") as drain,
    ):
        task_handle_availability_change.run("contact", "available", {"email": "ANA@example.com"})

    agent.refresh_from_db()
    assert agent.status_enum == Agent.StatusEnum.ONLINE
    accumulate.assert_called_once()
    drain.assert_called_once()
    assert AgentStatusHistory.objects.filter(agent=agent, new_status="online").exists()

    assert (
        task_handle_availability_change.run(
            "contact",
            "available",
            {"email": "ana@example.com"},
        )
        is None
    )


@pytest.mark.django_db
@override_settings(AGENT_STATUS_SYNC_ENABLED=False)
def test_availability_change_does_not_update_status_when_sync_disabled() -> None:
    agent = Agent.objects.create(
        name="Ana",
        agent_email="ana@example.com",
        hubspot_owner_id=10,
        status_enum=Agent.StatusEnum.AWAY,
    )

    with (
        patch("apps.support.sat_service.sat_accumulate_time") as accumulate,
        patch("apps.support.tasks.task_matchmaker_drain_queue.delay") as drain,
    ):
        task_handle_availability_change.run("contact", "available", {"email": "ana@example.com"})

    agent.refresh_from_db()
    assert agent.status_enum == Agent.StatusEnum.AWAY
    assert not AgentStatusHistory.objects.filter(agent=agent).exists()
    accumulate.assert_not_called()
    drain.assert_not_called()


def test_availability_change_fetches_contact_and_retries() -> None:
    client = Mock()
    client.get_contact_by_id.return_value = {"email": ""}
    with patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client):
        assert task_handle_availability_change.run("contact", "away", {}) is None

    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client", side_effect=RuntimeError("offline")),
        patch.object(task_handle_availability_change, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        task_handle_availability_change.run("contact", "away", {})


def test_team_and_novo_sync_tasks() -> None:
    with patch("apps.support.auto_assign_service.sync_hubspot_team_to_agents", return_value=3) as sync:
        assert task_sync_hubspot_team_members.run() == 3
    sync.assert_called_once()

    with patch(
        "apps.support.auto_assign_service.sync_novo_stage_tickets",
        return_value={"created": 1, "skipped": 0},
    ):
        assert task_sync_novo_stage_tickets.run() == {"created": 1, "skipped": 0}
    with (
        patch("apps.support.auto_assign_service.sync_novo_stage_tickets", side_effect=RuntimeError("offline")),
        patch.object(task_sync_novo_stage_tickets, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        task_sync_novo_stage_tickets.run()


@pytest.mark.django_db
def test_queue_metrics_aggregation() -> None:
    yesterday = timezone.localdate() - timedelta(days=1)
    entered_at = timezone.make_aware(datetime.combine(yesterday, datetime.min.time()))
    agent = Agent.objects.create(name="Ana", agent_email="ana@example.com", hubspot_owner_id=10)
    NewConversation.objects.create(hubspot_ticket_id="new", entered_queue_at=entered_at)
    AssignedConversation.objects.create(
        hubspot_ticket_id="assigned",
        agent=agent,
        hubspot_owner_id=10,
        agent_name="Ana",
        entered_queue_at=entered_at,
        assigned_at=entered_at,
        queue_wait_seconds=Decimal("10"),
        closed_at=entered_at,
        total_handle_time_minutes=Decimal("5"),
    )

    task_aggregate_queue_metrics.run()

    metrics = QueuePerformanceMetrics.objects.get(metric_date=yesterday)
    assert metrics.total_entered_queue == 1
    assert metrics.total_assigned == 1
    assert metrics.total_closed == 1
    assert metrics.p50_queue_wait_seconds == Decimal("10")
    assert metrics.assignments_by_agent == {"10": 1}


@pytest.mark.django_db
def test_reconcile_agent_counts_paths() -> None:
    with patch("apps.support.agent_sync_service.is_business_hours", return_value=False):
        assert task_reconcile_agent_counts.run() == {"skipped_off_hours": True}

    agent = Agent.objects.create(
        name="Ana",
        agent_email="ana@example.com",
        hubspot_owner_id=10,
        is_active=True,
        current_simultaneous_chats=4,
    )
    client = Mock()
    client.count_active_tickets_by_owner.return_value = 2
    with (
        patch("apps.support.agent_sync_service.is_business_hours", return_value=True),
        patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client),
    ):
        assert task_reconcile_agent_counts.run() == {"agents_checked": 1, "corrections": 1}
    agent.refresh_from_db()
    assert agent.current_simultaneous_chats == 2
