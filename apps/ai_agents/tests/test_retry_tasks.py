"""Tests for the scheduled lifecycle retry dispatcher."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
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
