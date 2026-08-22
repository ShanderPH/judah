"""Tests for durable webhook processing task retries."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.webhooks.tasks import (
    dispatch_n8n_outbox_event_task,
    hydrate_hubspot_message_event_task,
    poll_n8n_outbox_task,
    process_webhook_event_task,
    reconcile_hubspot_messages_task,
)


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


def test_new_inbound_tasks_delegate_to_durable_services(settings) -> None:
    settings.N8N_BOT_OUTBOX_BATCH_SIZE = 2
    with patch("apps.webhooks.reconciliation.hydrate_webhook_message_event", return_value=True):
        assert hydrate_hubspot_message_event_task.run("event-1") is True
    with patch("apps.webhooks.n8n_outbox.deliver_outbox_event", return_value=True):
        assert dispatch_n8n_outbox_event_task.run("outbox-1") is True
    with patch("apps.webhooks.reconciliation.reconcile_active_threads", return_value=3):
        assert reconcile_hubspot_messages_task.run() == 3


def test_outbox_poller_dispatches_bounded_batch(settings) -> None:
    settings.N8N_BOT_OUTBOX_BATCH_SIZE = 2
    with (
        patch("apps.webhooks.n8n_outbox.due_outbox_ids", return_value=["one", "two"]),
        patch("apps.webhooks.n8n_outbox.pending_outbox_count", return_value=7),
        patch("apps.webhooks.tasks.dispatch_n8n_outbox_event_task.delay") as delay,
        patch("apps.webhooks.metrics.emit_metric") as metric,
    ):
        assert poll_n8n_outbox_task.run() == 2
    assert delay.call_count == 2
    metric.assert_called_once_with("n8n_outbox_pending_total", 7, kind="gauge")
