"""Extended unit and integration tests for the support auto-assignment flow."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.integrations.hubspot.client import SUPPORT_PIPELINE_ID
from apps.support import auto_assign_service
from apps.support.models import Agent, AssignedConversation, AssignmentLog, NewConversation
from common.exceptions import ExternalServiceError


def _agent(
    owner_id: int,
    *,
    name: str = "Ana",
    status: str = Agent.StatusEnum.ONLINE,
    chats: int = 0,
) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}-{owner_id}@test.local",
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=chats,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=True,
    )


def _pending(ticket_id: str = "ticket-1") -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        pipeline_id=SUPPORT_PIPELINE_ID,
        entered_queue_at=timezone.now() - timedelta(minutes=2),
        contact_name="Maria",
        contact_email="maria@test.local",
        priority="HIGH",
        subject="Ajuda",
    )


def test_owner_and_timestamp_parsers_cover_supported_formats() -> None:
    assert auto_assign_service._safe_parse_owner_id("userId:123") == 123
    assert auto_assign_service._safe_parse_owner_id(456) == 456
    assert auto_assign_service._safe_parse_owner_id("StageCalculatedPropertiesRollup") is None
    assert auto_assign_service._safe_parse_owner_id(" null ") is None
    assert auto_assign_service._safe_parse_owner_id(None) is None
    assert auto_assign_service._parse_hubspot_timestamp("1711900000000") is not None
    assert auto_assign_service._parse_hubspot_timestamp("invalid") is None
    assert auto_assign_service._parse_hubspot_timestamp(None) is None


@pytest.mark.parametrize(
    ("ticket", "eligible"),
    [
        ({"id": "1", "pipeline": SUPPORT_PIPELINE_ID, "owner_id": ""}, True),
        ({"id": "2", "pipeline": "another", "owner_id": ""}, False),
        ({"id": "3", "pipeline": SUPPORT_PIPELINE_ID, "owner_id": "123"}, False),
        ({"id": "4", "pipeline": SUPPORT_PIPELINE_ID, "owner_id": "null"}, True),
    ],
)
def test_ticket_eligibility_rules(ticket: dict, eligible: bool) -> None:
    assert auto_assign_service._is_ticket_eligible(ticket) is eligible


@pytest.mark.django_db
def test_process_new_ticket_event_fetch_failure_and_ineligible() -> None:
    client = MagicMock()
    client.get_ticket_details.side_effect = ExternalServiceError("offline")
    with patch.object(auto_assign_service, "get_hubspot_client", return_value=client):
        assert auto_assign_service.process_new_ticket_event("ticket-1") is False

    client.get_ticket_details.side_effect = None
    client.get_ticket_details.return_value = {"id": "ticket-1", "pipeline": "wrong", "owner_id": ""}
    with patch.object(auto_assign_service, "get_hubspot_client", return_value=client):
        assert auto_assign_service.process_new_ticket_event("ticket-1") is False
    assert NewConversation.objects.count() == 0


@pytest.mark.django_db
def test_process_new_ticket_event_enqueues_idempotently() -> None:
    ticket = {
        "id": "ticket-1",
        "pipeline": SUPPORT_PIPELINE_ID,
        "owner_id": "",
        "contact_name": "Maria",
        "subject": "Ajuda",
    }
    client = MagicMock()
    client.get_ticket_details.return_value = ticket
    with (
        patch.object(auto_assign_service, "get_hubspot_client", return_value=client),
        patch.object(auto_assign_service, "attempt_auto_assign", return_value=True) as assign,
        patch.object(auto_assign_service, "_transition_lifecycle_best_effort") as transition,
    ):
        assert auto_assign_service.process_new_ticket_event("ticket-1", "1711900000000") is True
        assert auto_assign_service.process_new_ticket_event("ticket-1", "1711900000000") is True

    assert NewConversation.objects.count() == 1
    assert assign.call_count == 2
    assert transition.call_count == 2


@pytest.mark.django_db
def test_attempt_auto_assign_marks_queued_when_no_agent() -> None:
    pending = _pending()
    with (
        patch.object(auto_assign_service, "get_last_assigned_owner_id", return_value=None),
        patch.object(auto_assign_service, "select_next_agent", return_value=None),
    ):
        assert auto_assign_service.attempt_auto_assign(pending) is False

    pending.refresh_from_db()
    assert pending.queue_status == NewConversation.QueueStatus.QUEUED
    assert pending.assignment_attempts == 1
    assert pending.last_assignment_attempt_at is not None


@pytest.mark.django_db
def test_attempt_auto_assign_reselects_after_agent_goes_offline() -> None:
    pending = _pending()
    first = _agent(1, name="First", status=Agent.StatusEnum.OFFLINE)
    second = _agent(2, name="Second")
    client = MagicMock()
    with (
        patch.object(auto_assign_service, "get_last_assigned_owner_id", return_value=1),
        patch.object(auto_assign_service, "select_next_agent", side_effect=[first, second]),
        patch.object(auto_assign_service, "get_hubspot_client", return_value=client),
        patch.object(auto_assign_service, "_transition_lifecycle_best_effort"),
    ):
        assert auto_assign_service.attempt_auto_assign(pending) is True

    client.assign_ticket_owner.assert_called_once_with("ticket-1", 2)
    assigned = AssignedConversation.objects.get(hubspot_ticket_id="ticket-1")
    assert assigned.agent == second
    assert AssignmentLog.objects.filter(ticket_id="ticket-1", agent=second).exists()
    second.refresh_from_db()
    assert second.current_simultaneous_chats == 1


@pytest.mark.django_db
def test_attempt_auto_assign_queues_when_reselection_fails() -> None:
    pending = _pending()
    first = _agent(1, status=Agent.StatusEnum.OFFLINE)
    with (
        patch.object(auto_assign_service, "get_last_assigned_owner_id", return_value=None),
        patch.object(auto_assign_service, "select_next_agent", side_effect=[first, None]),
    ):
        assert auto_assign_service.attempt_auto_assign(pending) is False
    pending.refresh_from_db()
    assert pending.queue_status == NewConversation.QueueStatus.QUEUED
    assert pending.assignment_attempts == 1


@pytest.mark.django_db
def test_attempt_auto_assign_preserves_queue_on_hubspot_failure() -> None:
    pending = _pending()
    agent = _agent(1)
    client = MagicMock()
    client.assign_ticket_owner.side_effect = ExternalServiceError("offline")
    with (
        patch.object(auto_assign_service, "get_last_assigned_owner_id", return_value=None),
        patch.object(auto_assign_service, "select_next_agent", return_value=agent),
        patch.object(auto_assign_service, "get_hubspot_client", return_value=client),
    ):
        assert auto_assign_service.attempt_auto_assign(pending) is False
    assert NewConversation.objects.filter(pk=pending.pk).exists()
    assert not AssignedConversation.objects.exists()


def test_transition_lifecycle_is_best_effort() -> None:
    engine = MagicMock()
    engine.transition_by_ticket.side_effect = [True, False]
    with patch("apps.ai_agents.services.lifecycle.LifecycleEngine", return_value=engine):
        auto_assign_service._transition_lifecycle_best_effort("ticket-1", ["A", "B", "C"], reason="test")
    assert engine.transition_by_ticket.call_count == 2

    with patch("apps.ai_agents.services.lifecycle.LifecycleEngine", side_effect=RuntimeError("not ready")):
        auto_assign_service._transition_lifecycle_best_effort("ticket-1", ["A"], reason="test")


def test_assign_pending_tickets_maps_matchmaker_result() -> None:
    with patch(
        "apps.support.matchmaker_service.matchmaker_drain_queue",
        return_value={"assigned": 2, "remaining": 3, "total_pending": 5},
    ):
        assert auto_assign_service.assign_pending_tickets() == {
            "assigned": 2,
            "skipped": 3,
            "total_pending": 5,
        }


@pytest.mark.django_db
def test_sync_novo_stage_handles_external_failure() -> None:
    client = MagicMock()
    client.search_tickets_in_novo_stage.side_effect = ExternalServiceError("offline")
    with patch.object(auto_assign_service, "get_hubspot_client", return_value=client):
        result = auto_assign_service.sync_novo_stage_tickets()
    assert result["created"] == 0
    assert result["total_from_hubspot"] == 0
    assert "error" in result


@override_settings(NOVO_STAGE_SYNC_ENABLED=False)
def test_sync_novo_stage_stops_before_external_or_database_access() -> None:
    with patch.object(auto_assign_service, "get_hubspot_client") as get_client:
        result = auto_assign_service.sync_novo_stage_tickets()

    assert result == {
        "created": 0,
        "skipped": 0,
        "already_assigned": 0,
        "total_from_hubspot": 0,
        "disabled": True,
    }
    get_client.assert_not_called()


@pytest.mark.django_db
def test_sync_novo_stage_covers_created_skipped_assigned_and_reactivated() -> None:
    agent = _agent(10)
    AssignedConversation.objects.create(
        hubspot_ticket_id="assigned",
        agent=agent,
        hubspot_owner_id=10,
        agent_name=agent.name,
        assigned_at=timezone.now(),
    )
    NewConversation.objects.create(
        hubspot_ticket_id="existing",
        entered_queue_at=timezone.now(),
    )
    failed = NewConversation.objects.create(
        hubspot_ticket_id="reactivate",
        entered_queue_at=timezone.now(),
        queue_status=NewConversation.QueueStatus.FAILED,
        assignment_attempts=5,
        failure_code="hubspot_ticket_not_found",
        failure_message="gone",
    )
    tickets = [
        {"id": "owned", "owner_id": "99"},
        {"id": "existing", "owner_id": ""},
        {"id": "reactivate", "owner_id": ""},
        {"id": "assigned", "owner_id": ""},
        {
            "id": "new",
            "owner_id": "",
            "pipeline": SUPPORT_PIPELINE_ID,
            "entered_novo_at": "1711900000000",
            "subject": "Novo",
        },
    ]
    client = MagicMock()
    client.search_tickets_in_novo_stage.return_value = tickets
    with (
        patch.object(auto_assign_service, "get_hubspot_client", return_value=client),
        patch.object(
            auto_assign_service,
            "assign_pending_tickets",
            return_value={"assigned": 1, "skipped": 1, "total_pending": 2},
        ) as drain,
    ):
        result = auto_assign_service.sync_novo_stage_tickets()

    assert result == {"created": 2, "skipped": 2, "already_assigned": 1, "total_from_hubspot": 5}
    failed.refresh_from_db()
    assert failed.queue_status == NewConversation.QueueStatus.PENDING
    assert failed.assignment_attempts == 0
    assert NewConversation.objects.filter(hubspot_ticket_id="new").exists()
    drain.assert_called_once()


@pytest.mark.django_db
def test_sync_team_members_creates_only_valid_new_agents() -> None:
    _agent(1, name="Existing")
    client = MagicMock()
    client.get_team_members.return_value = [
        {"id": "1", "email": "existing@test.local", "first_name": "Existing"},
        {"id": "2", "email": "new@test.local", "first_name": "New", "last_name": "Agent"},
        {"id": "", "email": "missing@test.local"},
        {"id": "3", "email": ""},
    ]
    with patch.object(auto_assign_service, "get_hubspot_client", return_value=client):
        assert auto_assign_service.sync_hubspot_team_to_agents("team-1") == 1
    created = Agent.objects.get(hubspot_owner_id=2)
    assert created.name == "New Agent"
    assert created.team == "team_team-1"
    assert created.status_enum == Agent.StatusEnum.OFFLINE


@pytest.mark.django_db
def test_sync_team_members_handles_external_failure() -> None:
    client = MagicMock()
    client.get_team_members.side_effect = ExternalServiceError("offline")
    with patch.object(auto_assign_service, "get_hubspot_client", return_value=client):
        assert auto_assign_service.sync_hubspot_team_to_agents("team-1") == 0
