"""Unit coverage for AI Celery task orchestration."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
    client.delete.return_value = 0
    pipeline = Mock(return_value="coroutine")
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.api.webhooks._run_supervisor_pipeline", new=pipeline),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_supervisor_pipeline_task.run("ticket-1", True)
    pipeline.assert_called_once_with(
        "ticket-1",
        is_off_hours=True,
        enforce_ai_pipeline=False,
    )
    run.assert_called_once_with("coroutine")
    assert client.delete.call_count == 2

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


def test_supervisor_task_accepts_staging_dispatch_contract_and_queues_followup() -> None:
    client = Mock()
    client.set.return_value = True
    client.delete.side_effect = [1, 1]
    pipeline = Mock(return_value="coroutine")

    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch("apps.ai_agents.api.webhooks._run_supervisor_pipeline", new=pipeline),
        patch("apps.ai_agents.tasks.asyncio.run"),
        patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay") as followup,
    ):
        run_supervisor_pipeline_task.run("ticket-1", False, True, True)

    pipeline.assert_called_once_with(
        "ticket-1",
        is_off_hours=False,
        enforce_ai_pipeline=True,
    )
    followup.assert_called_once_with("ticket-1", False, True, True)


def test_supervisor_task_deduplicates_stage_and_marks_busy_customer_pending() -> None:
    stage_client = Mock()
    stage_client.set.return_value = False
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=stage_client),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_supervisor_pipeline_task.run("ticket-1", False, True, False)

    stage_client.set.assert_called_once_with(
        "salomao:supervisor:stage-trigger:ticket-1",
        "1",
        nx=True,
        ex=60,
    )
    run.assert_not_called()

    customer_client = Mock()
    customer_client.set.side_effect = [False, True]
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=customer_client),
        patch("apps.ai_agents.tasks.asyncio.run") as run,
    ):
        run_supervisor_pipeline_task.run("ticket-1", False, True, True)

    assert customer_client.set.call_count == 2
    customer_client.set.assert_any_call(
        "salomao:supervisor:pending:ticket-1",
        "1",
        ex=600,
    )
    run.assert_not_called()


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
        run_supervisor_pipeline_task.run("ticket-1", False, True, True)
    retry.assert_called_once()
    client.delete.assert_called_once()


def test_thread_task_success_duplicate_retry_and_lock_release_failure() -> None:
    client = Mock()
    client.set.return_value = True
    client.delete.return_value = 0
    context = {"ticket_id": ""}
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=AsyncMock(),
        ) as pipeline,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")
    pipeline.assert_awaited_once_with("thread-1", context=context)

    client.set.return_value = False
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(),
        ) as hydrate,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")
    hydrate.assert_not_awaited()

    client.set.return_value = True
    client.delete.return_value = 0
    client.delete.side_effect = redis.RedisError("delete failed")
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=AsyncMock(side_effect=RuntimeError("pipeline failed")),
        ),
        patch.object(run_salomao_v1_thread_pipeline_task, "retry", side_effect=RuntimeError("retried")),
        pytest.raises(RuntimeError, match="retried"),
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")


def test_thread_task_coalesces_busy_and_cross_ticket_followups() -> None:
    busy_client = Mock()
    busy_client.set.side_effect = [False, True]
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=busy_client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(),
        ) as hydrate,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")

    busy_client.set.assert_any_call(
        "salomao:supervisor:thread-pending:thread-1",
        "1",
        ex=600,
    )
    hydrate.assert_not_awaited()

    ticket_busy_client = Mock()
    ticket_busy_client.set.side_effect = [True, False, True]
    ticket_busy_client.delete.return_value = 0
    context = {"ticket_id": "ticket-1"}
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=ticket_busy_client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=AsyncMock(),
        ) as pipeline,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")

    ticket_busy_client.set.assert_any_call(
        "salomao:supervisor:thread-pending:thread-1",
        "1",
        ex=600,
    )
    pipeline.assert_not_awaited()


def test_thread_task_dispatches_one_canonical_followup() -> None:
    context = {"ticket_id": "ticket-1"}

    thread_pending_client = Mock()
    thread_pending_client.set.return_value = True
    thread_pending_client.delete.side_effect = [1, 1, 1, 1]
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=thread_pending_client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=AsyncMock(),
        ),
        patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as thread_followup,
        patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay") as ticket_followup,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")

    thread_followup.assert_called_once_with("thread-1")
    ticket_followup.assert_not_called()

    ticket_pending_client = Mock()
    ticket_pending_client.set.return_value = True
    ticket_pending_client.delete.side_effect = [1, 1, 0, 1]
    with (
        patch("apps.ai_agents.tasks._redis_client", return_value=ticket_pending_client),
        patch(
            "apps.ai_agents.services.hubspot.hydrate_thread_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "apps.ai_agents.api.webhooks._run_salomao_v1_thread_pipeline",
            new=AsyncMock(),
        ),
        patch("apps.ai_agents.tasks.run_salomao_v1_thread_pipeline_task.delay") as thread_followup,
        patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay") as ticket_followup,
    ):
        run_salomao_v1_thread_pipeline_task.run("thread-1")

    thread_followup.assert_not_called()
    ticket_followup.assert_called_once_with("ticket-1", False, True, True)


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
        patch(
            "apps.ai_agents.services.execution.ensure_conversation_instance",
            return_value=instance,
        ) as ensure_instance,
        patch(
            "apps.ai_agents.services.hubspot.build_conversation_context_from_hubspot_context",
            return_value=conversation_context,
        ),
        patch("apps.ai_agents.services.execution.request_human_handoff") as handoff,
    ):
        request_human_handoff_task.run(thread_id="thread-1", reason="risk")
    handoff.assert_called_once()
    assert ensure_instance.call_args.kwargs["session_id"] == "hubspot-thread-thread-1"

    with (
        patch(
            "apps.ai_agents.services.hubspot.hydrate_ticket_context",
            new=Mock(return_value="ticket-coro"),
        ),
        patch(
            "apps.ai_agents.tasks.asyncio.run",
            return_value={"ticket_id": "ticket-2", "thread_ids": ["thread-2"]},
        ),
        patch(
            "apps.ai_agents.services.execution.ensure_conversation_instance",
            return_value=instance,
        ) as ensure_instance,
        patch(
            "apps.ai_agents.services.hubspot.build_conversation_context_from_hubspot_context",
            return_value=conversation_context,
        ),
        patch("apps.ai_agents.services.execution.request_human_handoff") as handoff,
    ):
        request_human_handoff_task.run(ticket_id="ticket-2", reason="risk")
    handoff.assert_called_once()
    assert ensure_instance.call_args.kwargs["session_id"] == "hubspot-thread-thread-2"


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
