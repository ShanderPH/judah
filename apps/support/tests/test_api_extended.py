"""Direct coverage for support API helper endpoints."""

import inspect
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.support import api
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentLog,
    BusinessHoursConfig,
    NewConversation,
    QueuePerformanceMetrics,
    SpecialSchedule,
)
from apps.support.schemas import CreateSpecialScheduleRequest, CreateTicketRequest, UpdateTicketRequest


def _call(function, *args, **kwargs):
    return inspect.unwrap(function)(*args, **kwargs)


@pytest.mark.django_db
def test_ticket_and_queue_wrapper_endpoints() -> None:
    payload = CreateTicketRequest(ticket_id="EXT-1", priority="high", status="open")
    status, ticket = _call(api.create_ticket_endpoint, None, payload)
    assert status == 201
    assert _call(api.get_ticket_endpoint, None, "EXT-1") == ticket
    assert _call(api.update_ticket_endpoint, None, "EXT-1", UpdateTicketRequest(status="closed")).status == "closed"
    assert len(_call(api.list_tickets_endpoint, None, status="closed")) == 1

    with patch("apps.support.queue_service.get_queue_status", return_value={"pending_queue_depth": 0}) as queue:
        assert api.get_queue_status(None) == {"pending_queue_depth": 0}
    queue.assert_called_once()


@pytest.mark.django_db
def test_pending_assigned_metrics_and_sync_endpoints() -> None:
    agent = Agent.objects.create(
        name="Ana",
        agent_email="ana@example.com",
        hubspot_owner_id=10,
        status_enum=Agent.StatusEnum.ONLINE,
    )
    pending = NewConversation.objects.create(
        hubspot_ticket_id="pending",
        entered_queue_at=timezone.now(),
    )
    NewConversation.objects.create(
        hubspot_ticket_id="failed",
        entered_queue_at=timezone.now(),
        queue_status=NewConversation.QueueStatus.FAILED,
    )
    assigned = AssignedConversation.objects.create(
        hubspot_ticket_id="assigned",
        agent=agent,
        hubspot_owner_id=10,
        agent_name="Ana",
        assigned_at=timezone.now(),
    )
    QueuePerformanceMetrics.objects.create(metric_date=timezone.localdate(), total_assigned=1)

    assert list(_call(api.list_pending_conversations, None)) == [pending]
    assert list(_call(api.list_assigned_conversations, None, agent_owner_id=10, closed=False)) == [assigned]
    assert len(list(_call(api.list_queue_metrics, None, days=999))) == 1

    with patch(
        "apps.support.auto_assign_service.sync_novo_stage_tickets",
        return_value={"total_from_hubspot": 1, "created": 1, "skipped": 0},
    ):
        status, result = api.sync_novo_tickets(None)
    assert status == 202
    assert result["queued_for_assignment"] is True


@pytest.mark.django_db
def test_queue_health_builds_diagnostics() -> None:
    online = Agent.objects.create(
        name="Ana",
        agent_email="ana@example.com",
        hubspot_owner_id=10,
        status_enum=Agent.StatusEnum.ONLINE,
        current_simultaneous_chats=1,
    )
    Agent.objects.create(
        name="Bia",
        agent_email="bia@example.com",
        hubspot_owner_id=11,
        status_enum=Agent.StatusEnum.AWAY,
        current_simultaneous_chats=2,
    )
    NewConversation.objects.create(
        hubspot_ticket_id="pending",
        entered_queue_at=timezone.now() - timedelta(minutes=2),
        assignment_attempts=1,
    )
    AssignmentLog.objects.create(ticket_id="assigned", agent_name="Ana", hubspot_owner_id=10)

    with (
        patch("apps.support.queue_service.get_eligible_agents", return_value=[online]),
        patch("apps.support.queue_service.get_last_assigned_owner_id", return_value=10),
        patch("apps.support.assignment_readiness.evaluate_assignment_readiness", return_value={}),
    ):
        result = api.get_queue_health(None)

    assert result["summary"]["online_agents"] == 1
    assert result["summary"]["pending_queue_depth"] == 1
    assert result["summary"]["system_ok"] is False
    assert result["eligible_agents"][0]["is_last_assigned"] is True
    assert result["absent_agents"][0]["open_chats"] == 2


@pytest.mark.django_db
def test_business_hours_config_and_default() -> None:
    with patch("apps.support.agent_sync_service.is_business_hours", return_value=True):
        default = api.get_business_hours(None)
    assert default["name"] == "default (hardcoded)"
    assert default["monday"] == "09:00-17:50"
    assert default["is_currently_business_hours"] is True

    BusinessHoursConfig.objects.create(name="custom", monday_start=8, monday_end=17)
    with patch("apps.support.agent_sync_service.is_business_hours", return_value=False):
        configured = api.get_business_hours(None)
    assert configured["name"] == "custom"
    assert configured["monday"] == "08:00-17:00"
    assert configured["is_currently_business_hours"] is False


@pytest.mark.django_db
def test_special_schedule_create_list_update_and_delete() -> None:
    payload = CreateSpecialScheduleRequest(
        date=date(2026, 12, 25),
        schedule_type="closed",
        reason="Natal",
    )
    status, created = api.create_special_schedule(None, payload)
    assert status == 201
    assert created["date"] == "2026-12-25"
    assert api.list_special_schedules(None)[0]["reason"] == "Natal"

    updated_payload = CreateSpecialScheduleRequest(
        date=date(2026, 12, 25),
        schedule_type="custom",
        start_hour=10,
        end_hour=14,
        reason="Plantão",
    )
    _, updated = api.create_special_schedule(None, updated_payload)
    assert updated["schedule_type"] == "custom"
    assert SpecialSchedule.objects.count() == 1

    assert api.delete_special_schedule(None, str(updated["id"])) == (204, None)
    assert SpecialSchedule.objects.count() == 0
