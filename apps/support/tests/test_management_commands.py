"""Coverage for support and lifecycle management commands."""

import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.support.models import Agent, AssignmentLog, NewConversation


def _agent(name: str, owner_id: int, status: str, chats: int = 0, max_chats: int = 5) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}@example.com",
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=chats,
        max_simultaneous_chats=max_chats,
        auto_assign_enabled=status != Agent.StatusEnum.OFFLINE,
    )


@pytest.mark.django_db
def test_check_assignment_system_table_covers_agents_queue_logs_and_health() -> None:
    online = _agent("Ana", 10, Agent.StatusEnum.ONLINE, chats=1)
    _agent("Bia", 11, Agent.StatusEnum.AWAY, chats=2, max_chats=2)
    pending = NewConversation.objects.create(
        hubspot_ticket_id="ticket-1",
        entered_queue_at=timezone.now() - timedelta(minutes=5),
        priority="HIGH",
        contact_name="Cliente",
    )
    AssignmentLog.objects.create(
        ticket_id="assigned-1",
        agent=online,
        agent_name=online.name,
        hubspot_owner_id=online.hubspot_owner_id,
        queue_wait_seconds=12,
    )
    stdout = io.StringIO()

    with (
        patch(
            "apps.support.management.commands.check_assignment_system.get_eligible_agents",
            return_value=[online],
        ),
        patch(
            "apps.support.management.commands.check_assignment_system.get_last_assigned_owner_id",
            return_value=online.hubspot_owner_id,
        ),
    ):
        call_command("check_assignment_system", tickets=10, format="table", stdout=stdout)

    output = stdout.getvalue()
    assert "AGENTES" in output
    assert pending.hubspot_ticket_id in output
    assert "CAPACIDADE MAX." in output
    assert "Apenas 1 agente elegivel" in output


@pytest.mark.django_db
def test_check_assignment_system_json_output() -> None:
    online = _agent("Ana", 10, Agent.StatusEnum.ONLINE)
    NewConversation.objects.create(
        hubspot_ticket_id="ticket-json",
        entered_queue_at=timezone.now() - timedelta(seconds=10),
    )
    stdout = io.StringIO()
    with (
        patch(
            "apps.support.management.commands.check_assignment_system.get_eligible_agents",
            return_value=[online],
        ),
        patch(
            "apps.support.management.commands.check_assignment_system.get_last_assigned_owner_id",
            return_value=None,
        ),
    ):
        call_command("check_assignment_system", tickets=5, format="json", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["summary"]["total_agents"] == 1
    assert payload["summary"]["pending_queue_depth"] == 1
    assert payload["agents"][0]["eligible"] is True


@pytest.mark.django_db
def test_sync_novo_command_success_error_and_assignment() -> None:
    stdout = io.StringIO()
    with (
        patch(
            "apps.support.auto_assign_service.sync_novo_stage_tickets",
            return_value={"total_from_hubspot": 2, "created": 1, "skipped": 1},
        ),
        patch("apps.support.auto_assign_service.assign_pending_tickets", return_value={"assigned": 1, "skipped": 0}),
        patch("apps.support.models.NewConversation.objects.count", return_value=1),
    ):
        call_command("sync_novo_conversations", assign=True, stdout=stdout)
    assert "conversation(s) instanced and queued" in stdout.getvalue()
    assert "Assigned: 1" in stdout.getvalue()

    stderr = io.StringIO()
    with patch(
        "apps.support.auto_assign_service.sync_novo_stage_tickets",
        return_value={"error": "offline"},
    ):
        call_command("sync_novo_conversations", stderr=stderr)
    assert "HubSpot fetch failed" in stderr.getvalue()


@pytest.mark.django_db
def test_sync_novo_command_dry_run_covers_all_skip_reasons() -> None:
    tickets = [
        {"id": "owned", "owner_id": "10", "subject": "Owned"},
        {"id": "new", "owner_id": "", "subject": "New"},
        {"id": "assigned", "owner_id": "", "subject": "Assigned"},
        {"id": "fresh", "owner_id": "", "subject": "Fresh"},
    ]
    client = Mock()
    client.search_tickets_in_novo_stage.return_value = tickets
    new_filter = Mock()
    new_filter.exists.side_effect = [False, True, False, False]
    assigned_filter = Mock()
    assigned_filter.exists.side_effect = [False, False, True, False]
    stdout = io.StringIO()

    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client),
        patch("apps.support.models.NewConversation.objects.filter", return_value=new_filter),
        patch("apps.support.models.AssignedConversation.objects.filter", return_value=assigned_filter),
    ):
        call_command("sync_novo_conversations", dry_run=True, stdout=stdout)

    output = stdout.getvalue()
    assert "already has owner" in output
    assert "already in new_conversations" in output
    assert "already in assigned_conversations" in output
    assert "would queue" in output


def test_lifecycle_watchdog_command_formats_result() -> None:
    stdout = io.StringIO()
    with patch(
        "apps.ai_agents.management.commands.run_lifecycle_watchdog.run_lifecycle_watchdog",
        return_value=SimpleNamespace(scanned=3, marked_retryable=2, marked_terminal=1),
    ) as watchdog:
        call_command("run_lifecycle_watchdog", limit=10, max_failures=4, stdout=stdout)

    watchdog.assert_called_once_with(limit=10, max_failures=4)
    assert "scanned=3" in stdout.getvalue()
