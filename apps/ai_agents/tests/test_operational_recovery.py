"""Tests for bounded, auditable single-ticket recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.ai_agents.models import AgentRun, ConversationInstance, ToolCallAuditLog
from apps.ai_agents.services.recovery import execute_ticket_recovery, inspect_ticket_recovery


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_recovery_inspection_revalidates_canonical_turn_without_writes() -> None:
    instance = await ConversationInstance.objects.acreate(
        idempotency_key="conversation:thread:recovery-thread",
        hubspot_thread_id="recovery-thread",
        hubspot_ticket_id="recovery-ticket",
    )
    context = {
        "ticket_id": "recovery-ticket",
        "thread_ids": ["recovery-thread"],
        "pipeline": "ai-pipeline",
        "pipeline_stage": "ai-stage",
        "owner_id": "",
        "errors": [],
        "conversation_history": [
            {
                "id": "recovery-message",
                "thread_id": "recovery-thread",
                "direction": "INCOMING",
                "text": "Ainda preciso de ajuda",
                "created_at": "2026-07-28T21:45:07.273Z",
            }
        ],
    }

    with (
        patch(
            "apps.ai_agents.services.recovery.hydrate_ticket_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.services.recovery.evaluate_salomao_ticket_eligibility",
            return_value={"eligible": True, "reason": "eligible", "retryable": False},
        ),
    ):
        result = await inspect_ticket_recovery("recovery-ticket")

    assert result["eligible"] is True
    assert result["instance_id"] == str(instance.pk)
    assert result["customer_turn"]["last_message_id"] == "recovery-message"
    assert await AgentRun.objects.acount() == 0
    assert await ToolCallAuditLog.objects.acount() == 0


@pytest.mark.django_db
def test_execute_recovery_is_idempotent_and_audited() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:execute-recovery",
        hubspot_thread_id="execute-recovery",
        hubspot_ticket_id="execute-ticket",
    )
    inspection = {
        "eligible": True,
        "reasons": [],
        "ticket_id": "execute-ticket",
        "thread_id": "execute-recovery",
        "instance_id": str(instance.pk),
        "customer_turn": {"last_message_id": "execute-message"},
        "owner_present": False,
        "provider_errors": [],
    }

    with patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as enqueue:
        first = execute_ticket_recovery(inspection=inspection, operator="tiago@example.com")
        duplicate = execute_ticket_recovery(inspection=inspection, operator="tiago@example.com")

    assert first["scheduled"] is True
    assert duplicate["deduplicated"] is True
    enqueue.assert_called_once_with("execute-recovery")
    assert AgentRun.objects.filter(agent_name="OperationalRecovery", status=AgentRun.Status.SUCCEEDED).count() == 1
    assert (
        ToolCallAuditLog.objects.filter(
            tool_name="schedule_operational_recovery",
            status=ToolCallAuditLog.Status.SUCCEEDED,
        ).count()
        == 1
    )
