"""Management-command contract for safe single-ticket recovery."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_recovery_command_is_read_only_by_default() -> None:
    inspection = {
        "ticket_id": "ticket-1",
        "thread_id": "thread-1",
        "instance_id": "instance-1",
        "customer_turn": {"last_message_id": "message-1"},
        "pipeline": "pipeline-1",
        "pipeline_stage": "stage-1",
        "owner_present": False,
        "eligible": True,
        "reasons": [],
        "provider_errors": [],
    }
    stdout = StringIO()

    with (
        patch(
            "apps.ai_agents.management.commands.recover_suppressed_turn.inspect_ticket_recovery",
            new=AsyncMock(return_value=inspection),
        ) as inspect,
        patch("apps.ai_agents.management.commands.recover_suppressed_turn.execute_ticket_recovery") as execute,
    ):
        call_command(
            "recover_suppressed_turn",
            ticket_id="ticket-1",
            operator="operator@example.com",
            stdout=stdout,
        )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry-run"
    assert payload["eligible"] is True
    inspect.assert_awaited_once_with("ticket-1")
    execute.assert_not_called()


@pytest.mark.django_db
def test_recovery_command_requires_execute_flag_for_dispatch() -> None:
    inspection = {
        "ticket_id": "ticket-2",
        "thread_id": "thread-2",
        "instance_id": "instance-2",
        "customer_turn": {"last_message_id": "message-2"},
        "pipeline": "pipeline-1",
        "pipeline_stage": "stage-1",
        "owner_present": False,
        "eligible": True,
        "reasons": [],
        "provider_errors": [],
    }
    stdout = StringIO()

    with (
        patch(
            "apps.ai_agents.management.commands.recover_suppressed_turn.inspect_ticket_recovery",
            new=AsyncMock(return_value=inspection),
        ),
        patch(
            "apps.ai_agents.management.commands.recover_suppressed_turn.execute_ticket_recovery",
            return_value={"scheduled": True, "deduplicated": False, "audit_id": "audit-1"},
        ) as execute,
    ):
        call_command(
            "recover_suppressed_turn",
            ticket_id="ticket-2",
            operator="operator@example.com",
            execute=True,
            stdout=stdout,
        )

    assert '"mode": "execute"' in stdout.getvalue()
    assert '"scheduled": true' in stdout.getvalue()
    execute.assert_called_once_with(
        inspection=inspection,
        operator="operator@example.com",
    )
