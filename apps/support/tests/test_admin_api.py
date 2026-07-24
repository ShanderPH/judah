"""Direct service-level tests for support administrative endpoints."""

import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.support import admin_api
from apps.support.models import (
    Agent,
    AgentDailyTimeLog,
    AgentMetrics,
    AssignedConversation,
    ConversationReassignment,
    NewConversation,
)
from apps.support.schemas import (
    CreateAgentRequest,
    ForceReassignRequest,
    ManualAssignRequest,
    UpdateAgentRequest,
)
from common.exceptions import ConflictError, NotFoundError


def _request():
    return SimpleNamespace(auth=SimpleNamespace(role="admin", email="admin@example.com"))


def _call(function, *args, **kwargs):
    return inspect.unwrap(function)(*args, **kwargs)


def _agent(name: str, email: str, owner_id: int) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=email,
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=True,
    )


@pytest.mark.django_db
def test_agent_crud_filters_and_conflicts() -> None:
    request = _request()
    status, created = _call(
        admin_api.create_agent,
        request,
        CreateAgentRequest(
            name="Ana",
            agent_email="ana@example.com",
            hubspot_owner_id=10,
            team="N1",
        ),
    )
    assert status == 201
    assert created.status_enum == Agent.StatusEnum.OFFLINE

    assert list(_call(admin_api.list_agents, request, status="offline", team="N1", is_active=True)) == [created]
    assert _call(admin_api.retrieve_agent, request, str(created.pk)) == created

    with pytest.raises(ConflictError):
        _call(
            admin_api.create_agent,
            request,
            CreateAgentRequest(name="Owner duplicate", agent_email="other@example.com", hubspot_owner_id=10),
        )
    with pytest.raises(ConflictError):
        _call(
            admin_api.create_agent,
            request,
            CreateAgentRequest(name="Email duplicate", agent_email="ANA@example.com", hubspot_owner_id=11),
        )
    with pytest.raises(NotFoundError):
        _call(admin_api.retrieve_agent, request, "00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_agent_update_inactivate_reactivate_and_validation() -> None:
    request = _request()
    agent = _agent("Ana", "ana@example.com", 10)
    updated = _call(
        admin_api.update_agent,
        request,
        str(agent.pk),
        UpdateAgentRequest(
            name="Ana Atualizada",
            team="N2",
            manager_email="manager@example.com",
            timezone="UTC",
            max_simultaneous_chats=8,
            auto_assign_enabled=False,
            is_active=False,
            status_enum="away",
        ),
    )
    assert updated.name == "Ana Atualizada"
    assert updated.max_simultaneous_chats == 8
    assert updated.status_enum == Agent.StatusEnum.ONLINE

    inactive = _call(admin_api.inactivate_agent, request, str(agent.pk))
    assert inactive.is_active is False
    assert inactive.auto_assign_enabled is False
    assert inactive.status_enum == Agent.StatusEnum.ONLINE
    active = _call(admin_api.reactivate_agent, request, str(agent.pk))
    assert active.is_active is True

    with pytest.raises(NotFoundError):
        _call(admin_api.update_agent, request, "00000000-0000-0000-0000-000000000000", UpdateAgentRequest())
    with pytest.raises(NotFoundError):
        _call(admin_api.inactivate_agent, request, "00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError):
        _call(admin_api.reactivate_agent, request, "00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_metrics_time_logs_and_reassignment_queries() -> None:
    request = _request()
    first = _agent("Ana", "ana@example.com", 10)
    second = _agent("Bia", "bia@example.com", 11)
    now = timezone.now()
    AgentMetrics.objects.create(
        agent_id=10,
        average_ticket_time_min=12,
        total_chats=5,
        chats_closed=4,
        first_response_time_avg_min=Decimal("3.50"),
        resolution_rate=Decimal("80.00"),
        customer_satisfaction_avg=Decimal("4.50"),
        last_time_updated=now,
    )
    AgentMetrics.objects.create(
        agent_id=11,
        average_ticket_time_min=18,
        total_chats=3,
        chats_closed=2,
        last_time_updated=now,
    )
    AgentDailyTimeLog.objects.create(
        agent=first,
        log_date=timezone.localdate(),
        online_time_seconds=100,
        away_time_seconds=20,
        status_transitions=2,
    )
    ConversationReassignment.objects.create(
        hubspot_ticket_id="ticket-1",
        from_agent=first,
        from_hubspot_owner_id=10,
        from_agent_name="Ana",
        to_agent=second,
        to_hubspot_owner_id=11,
        to_agent_name="Bia",
        reassigned_at=now,
    )

    assert len(list(_call(admin_api.list_agent_metrics, request, str(first.pk)))) == 1
    assert len(list(_call(admin_api.list_all_agent_metrics, request, days=999))) == 2
    summary = _call(admin_api.agent_metrics_summary, request, days=30)
    assert summary["total_chats"] == 8
    assert summary["total_chats_closed"] == 6
    assert summary["avg_handle_time_min"] == 15.0
    assert len(list(_call(admin_api.list_agent_time_logs, request, str(first.pk), days=999))) == 1
    assert len(list(_call(admin_api.list_time_logs, request, days=999))) == 1
    assert len(list(_call(admin_api.list_reassignments, request, agent_owner_id=10, days=999))) == 1
    transfers = _call(admin_api.reassignments_summary, request, days=999)
    assert transfers[0]["hubspot_owner_id"] in {10, 11}
    assert sum(item["transferred_in"] for item in transfers) == 1
    assert sum(item["transferred_out"] for item in transfers) == 1

    with pytest.raises(NotFoundError):
        _call(admin_api.list_agent_metrics, request, "00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError):
        _call(admin_api.list_agent_time_logs, request, "00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_manual_assignment_and_force_reassignment() -> None:
    request = _request()
    first = _agent("Ana", "ana@example.com", 10)
    second = _agent("Bia", "bia@example.com", 11)
    NewConversation.objects.create(
        hubspot_ticket_id="ticket-1",
        entered_queue_at=timezone.now(),
        subject="Assunto",
    )

    reservation = SimpleNamespace(attempt=SimpleNamespace(pk="attempt-1", cycle_id=None))
    with (
        patch("apps.support.admin_api._ensure_agent_is_currently_eligible"),
        patch(
            "apps.support.durable_assignment_service.reserve_manual_assignment",
            return_value=reservation,
        ) as reserve,
        patch(
            "apps.support.durable_assignment_service.execute_assignment_attempt",
            return_value="assigned",
        ) as execute,
    ):
        result = _call(
            admin_api.manual_assign,
            request,
            ManualAssignRequest(hubspot_ticket_id="ticket-1", agent_id=first.pk),
        )
    assert result["success"] is True
    reserve.assert_called_once()
    execute.assert_called_once_with("attempt-1")

    AssignedConversation.objects.create(
        hubspot_ticket_id="ticket-1",
        agent=first,
        hubspot_owner_id=first.hubspot_owner_id,
        agent_name=first.name,
        assigned_at=timezone.now(),
    )

    with (
        patch("apps.support.admin_api._ensure_agent_is_currently_eligible"),
        patch("apps.support.admin_api._hubspot_assign"),
        patch("apps.support.admin_api.decrement_agent_chat_count") as decrement,
        patch("apps.support.admin_api.increment_agent_chat_count") as increment,
    ):
        reassigned = _call(
            admin_api.force_reassign,
            request,
            ForceReassignRequest(hubspot_ticket_id="ticket-1", target_agent_id=second.pk, reason="capacity"),
        )
    assert reassigned["agent_name"] == "Bia"
    decrement.assert_called_once_with(first)
    increment.assert_called_once_with(second)
    assert ConversationReassignment.objects.filter(hubspot_ticket_id="ticket-1").exists()

    with patch("apps.support.admin_api._ensure_agent_is_currently_eligible"):
        no_op = _call(admin_api._force_reassign_internal, "ticket-1", second)
    assert "no-op" in no_op["detail"]


@pytest.mark.django_db
def test_assignment_errors_and_hubspot_best_effort() -> None:
    request = _request()
    agent = _agent("Ana", "ana@example.com", 10)
    with pytest.raises(NotFoundError):
        _call(
            admin_api.manual_assign,
            request,
            ManualAssignRequest(hubspot_ticket_id="missing", agent_id=agent.pk),
        )
    with pytest.raises(NotFoundError):
        _call(admin_api._force_reassign_internal, "missing", agent)
    with pytest.raises(NotFoundError):
        _call(
            admin_api.force_reassign,
            request,
            ForceReassignRequest(
                hubspot_ticket_id="missing",
                target_agent_id="00000000-0000-0000-0000-000000000000",
                reason="capacity",
            ),
        )

    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client", side_effect=RuntimeError("offline")),
        pytest.raises(RuntimeError, match="offline"),
    ):
        admin_api._hubspot_assign("ticket", 10)
