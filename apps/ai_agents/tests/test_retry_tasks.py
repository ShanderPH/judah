"""Tests for the scheduled lifecycle retry dispatcher."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance, ToolCallAuditLog
from apps.ai_agents.tasks import retry_failed_lifecycle_instances_task


@pytest.mark.django_db
def test_retry_dispatcher_redispatches_due_thread() -> None:
    ConversationInstance.objects.create(
        idempotency_key="conversation:thread:retry-thread",
        hubspot_thread_id="retry-thread",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=1,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as delay:
        result = retry_failed_lifecycle_instances_task()

    assert result["redispatched"] == 1
    delay.assert_called_once_with("retry-thread")


@pytest.mark.django_db
def test_retry_dispatcher_hands_off_exhausted_ticket() -> None:
    ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:retry-ticket",
        hubspot_ticket_id="retry-ticket",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=3,
        current_error="provider unavailable",
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("apps.ai_agents.services.execution.request_human_handoff") as handoff:
        result = retry_failed_lifecycle_instances_task()

    assert result["handed_off"] == 1
    handoff.assert_called_once()


@pytest.mark.django_db
def test_retry_dispatcher_schedules_pending_effect_instead_of_model() -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:thread:pending-effect",
        hubspot_thread_id="pending-effect",
        hubspot_ticket_id="ticket-pending-effect",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=1,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    ToolCallAuditLog.objects.create(
        instance=instance,
        tool_name="update_ticket_stage",
        input={
            "ticket_id": "ticket-pending-effect",
            "pipeline_id": "ai-pipeline",
            "stage_id": "closed",
        },
        status=ToolCallAuditLog.Status.FAILED,
        idempotency_key="ai-resolution-close:v1:pending-effect",
    )

    with (
        patch("apps.ai_agents.tasks.retry_pending_ticket_effect_task.delay") as effect_delay,
        patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as model_delay,
    ):
        result = retry_failed_lifecycle_instances_task()

    assert result["effect_replays"] == 1
    assert result["redispatched"] == 0
    effect_delay.assert_called_once_with(str(instance.pk))
    model_delay.assert_not_called()
