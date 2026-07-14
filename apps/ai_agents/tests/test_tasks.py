"""Concurrency behavior for durable Supervisor tasks."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.tasks import run_lifecycle_watchdog_task, run_supervisor_pipeline_task


def test_busy_stage_event_is_deduplicated(monkeypatch) -> None:
    redis_client = Mock()
    redis_client.set.side_effect = [True, False]
    monkeypatch.setattr("apps.ai_agents.tasks._redis_client", lambda: redis_client)

    run_supervisor_pipeline_task.run("ticket-1", False, True, False)

    assert redis_client.set.call_count == 2


def test_repeated_stage_trigger_is_coalesced_before_lock(monkeypatch) -> None:
    redis_client = Mock()
    redis_client.set.return_value = False
    monkeypatch.setattr("apps.ai_agents.tasks._redis_client", lambda: redis_client)

    run_supervisor_pipeline_task.run("ticket-1", False, True, False)

    redis_client.set.assert_called_once_with(
        "salomao:supervisor:stage-trigger:ticket-1",
        "1",
        nx=True,
        ex=60,
    )


def test_busy_customer_message_marks_followup_pending(monkeypatch) -> None:
    redis_client = Mock()
    redis_client.set.side_effect = [False, True]
    monkeypatch.setattr("apps.ai_agents.tasks._redis_client", lambda: redis_client)

    run_supervisor_pipeline_task.run("ticket-1", False, True, True)

    assert redis_client.set.call_count == 2
    pending_call = redis_client.set.call_args_list[1]
    assert pending_call.args[0] == "salomao:supervisor:pending:ticket-1"


@pytest.mark.django_db
def test_lifecycle_watchdog_dispatches_due_ticket_retry(monkeypatch) -> None:
    instance = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:retry-1",
        hubspot_ticket_id="retry-1",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        last_activity_at=timezone.now(),
        next_retry_at=timezone.now() - timedelta(seconds=1),
        current_error="provider timeout",
    )
    delay = Mock()
    monkeypatch.setattr("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay", delay)

    result = run_lifecycle_watchdog_task.run()

    instance.refresh_from_db()
    assert result["retries_dispatched"] == 1
    assert instance.state == ConversationInstance.State.CONTEXT_HYDRATING
    assert instance.next_retry_at is None
    delay.assert_called_once_with("retry-1", False, True, True)
