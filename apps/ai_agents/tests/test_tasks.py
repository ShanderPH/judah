"""Unit coverage for AI Celery task orchestration."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import redis
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance
from apps.ai_agents.tasks import (
    request_human_handoff_task,
    retry_failed_lifecycle_instances_task,
    run_lifecycle_watchdog_task,
    run_salomao_v1_thread_pipeline_task,
    run_supervisor_pipeline_task,
)


def test_supervisor_task_success_duplicate_and_lock_failure() -> None:
    client = Mock()
    client.set.return_value = True
    pipeline = Mock(return_value="coroutine")
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.api.webhooks._run_supervisor_pipeline", new=pipeline),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_supervisor_pipeline_task.run("ticket-1", True)
    pipeline.assert_called_once_with("ticket-1", is_off_hours=True)
    run.assert_called_once_with("coroutine")
    client.delete.assert_called_once()

    client.reset_mock()
    client.set.return_value = False
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        assert run_supervisor_pipeline_task.run("ticket-1") is None
    run.assert_not_called()

    with (
        patch("apps.ai_agents.tasks._redis_client", side_effect=redis.RedisError("offline")),
        patch("apps.ai_agents.api.webhooks._run_supervisor_pipeline", new=Mock(return_value="coroutine")),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_supervisor_pipeline_task.run("ticket-1")
    run.assert_called_once_with("coroutine")


def test_supervisor_task_retries_and_tolerates_lock_release_failure() -> None:
    client = Mock()
    client.set.return_value = True
    client.delete.side_effect = redis.RedisError("delete failed")
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.api.webhooks._run_supervisor_pipeline", new=Mock(return_value="coroutine")),
        patch("apps.ai_agents.tasks.asyncio.run", side_effect=RuntimeError("pipeline failed")),
        patch.object(run_supervisor_pipeline_task, "retry", side_effect=RuntimeError("retried")) as retry,
        pytest.raises(RuntimeError, match="retried"),
    ):
        run_supervisor_pipeline_task.run("ticket-1")
    retry.assert_called_once()
    client.delete.assert_called_once()


def test_thread_task_success_duplicate_retry_and_lock_release_failure() -> None:
    client = Mock()
    client.set.return_value = True
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=Mock(return_value="coroutine"),
        ),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")
    run.assert_called_once_with("coroutine")

    client.set.return_value = False
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")
    run.assert_not_called()

    client.set.return_value = True
    client.delete.side_effect = redis.RedisError("delete failed")
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=Mock(return_value="coroutine"),
        ),
        patch("apps.ai_agents.tasks.asyncio.run", side_effect=RuntimeError("pipeline failed")),
        patch.object(run_salomao_v1_thread_pipeline_task, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")


def test_handoff_task_hydrates_thread_and_ticket() -> None:
    instance = Mock()
    conversation_context = Mock()
    with (
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=Mock(return_value="thread-coro"),
        ),
        patch(
            "apps.ai_agents.tasks.asyncio.run",
            return_value={"ticket_id": "ticket-1", "thread_ids": ["thread-1"]},
        ),
        patch("apps.ai_agents.services.execution.ensure_conversation_instance", return_value=instance),
        patch(
            "apps.ai_agents.services.hubspot.build_conversation_context_from_hubspot_context",
            return_value=conversation_context,
        ),
        patch("apps.ai_agents.services.execution.request_human_handoff") as handoff,
    ):
        request_human_handoff_task.run(thread_id="thread-1", reason="risk")
    handoff.assert_called_once()

    with (
        patch(
            "apps.ai_agents.services.hubspot.hydrate_ticket_context",
            new=Mock(return_value="ticket-coro"),
        ),
        patch("apps.ai_agents.tasks.asyncio.run", return_value={"ticket_id": "ticket-2"}),
        patch("apps.ai_agents.services.execution.ensure_conversation_instance", return_value=instance),
        patch(
            "apps.ai_agents.services.hubspot.build_conversation_context_from_hubspot_context",
            return_value=conversation_context,
        ),
        patch("apps.ai_agents.services.execution.request_human_handoff") as handoff,
    ):
        request_human_handoff_task.run(ticket_id="ticket-2", reason="risk")
    handoff.assert_called_once()


def test_handoff_task_retries_invalid_request() -> None:
    with (
        patch.object(request_human_handoff_task, "retry", side_effect=RuntimeError("retried")) as retry,
        pytest.raises(RuntimeError, match="retried"),
    ):
        request_human_handoff_task.run(reason="missing identifiers")
    retry.assert_called_once()


def test_watchdog_task_maps_result() -> None:
    with patch(
        "apps.ai_agents.services.watchdog.run_lifecycle_watchdog",
        return_value=SimpleNamespace(scanned=3, marked_retryable=2, marked_terminal=1),
    ):
        assert run_lifecycle_watchdog_task.run() == {
            "scanned": 3,
            "marked_retryable": 2,
            "marked_terminal": 1,
        }


@pytest.mark.django_db
def test_retry_dispatcher_ticket_and_terminal_paths() -> None:
    ticket = ConversationInstance.objects.create(
        idempotency_key="conversation:ticket:retry-ticket-task",
        hubspot_ticket_id="retry-ticket-task",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=1,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    no_identifier = ConversationInstance.objects.create(
        idempotency_key="conversation:no-id",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=1,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    exhausted = ConversationInstance.objects.create(
        idempotency_key="conversation:exhausted-no-id",
        state=ConversationInstance.State.FAILED_RETRYABLE,
        failure_count=3,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )

    with patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay") as delay:
        result = retry_failed_lifecycle_instances_task.run(limit=10)

    assert result == {"scanned": 3, "redispatched": 1, "handed_off": 0, "terminal": 2}
    delay.assert_called_once_with(ticket.hubspot_ticket_id, False)
    no_identifier.refresh_from_db()
    exhausted.refresh_from_db()
    assert no_identifier.state == ConversationInstance.State.FAILED_TERMINAL
    assert exhausted.state == ConversationInstance.State.FAILED_TERMINAL
