"""Tests for durable webhook processing task retries."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.webhooks.tasks import process_webhook_event_task


def test_webhook_task_returns_true_on_success() -> None:
    with patch("apps.webhooks.tasks.process_webhook_event", return_value=True):
        assert process_webhook_event_task.run("event-1") is True


def test_webhook_task_stops_when_event_is_missing_or_exhausted() -> None:
    manager = process_webhook_event_task.__module__
    with (
        patch("apps.webhooks.tasks.process_webhook_event", return_value=False),
        patch("apps.webhooks.tasks.WebhookEvent.objects.filter") as filtered,
    ):
        filtered.return_value.first.return_value = None
        assert process_webhook_event_task.run("missing") is False

        filtered.return_value.first.return_value = SimpleNamespace(retry_count=3)
        assert process_webhook_event_task.run("exhausted") is False
    assert manager == "apps.webhooks.tasks"


def test_webhook_task_schedules_retry() -> None:
    event = SimpleNamespace(retry_count=1, error_message="temporary")
    with (
        patch("apps.webhooks.tasks.process_webhook_event", return_value=False),
        patch("apps.webhooks.tasks.WebhookEvent.objects.filter") as filtered,
        patch.object(process_webhook_event_task, "retry", side_effect=RuntimeError("retried")) as retry,
        pytest.raises(RuntimeError, match="retried"),
    ):
        filtered.return_value.first.return_value = event
        process_webhook_event_task.run("event-1")

    retry.assert_called_once()
