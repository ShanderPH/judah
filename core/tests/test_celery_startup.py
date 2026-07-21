"""Tests for Celery startup behavior."""

from unittest.mock import patch

from django.test import override_settings

from core.celery import on_worker_ready


@override_settings(NOVO_STAGE_SYNC_ENABLED=False)
def test_worker_ready_does_not_dispatch_novo_sync_when_disabled() -> None:
    with patch("apps.support.tasks.task_sync_novo_stage_tickets.delay") as delay:
        on_worker_ready()

    delay.assert_not_called()


@override_settings(NOVO_STAGE_SYNC_ENABLED=True)
def test_worker_ready_dispatches_novo_sync_when_enabled() -> None:
    with patch("apps.support.tasks.task_sync_novo_stage_tickets.delay") as delay:
        on_worker_ready()

    delay.assert_called_once_with()
