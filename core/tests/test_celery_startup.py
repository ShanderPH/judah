"""Tests for Celery startup behavior."""

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from core.celery import on_worker_ready


def test_sat_and_database_scheduler_polling_are_bounded() -> None:
    heartbeat = settings.CELERY_BEAT_SCHEDULE["sat-heartbeat"]

    assert heartbeat["schedule"] == settings.SAT_HEARTBEAT_INTERVAL_SECONDS
    assert heartbeat["options"]["expires"] == settings.SAT_HEARTBEAT_INTERVAL_SECONDS
    assert settings.SAT_HEARTBEAT_INTERVAL_SECONDS >= 20
    assert settings.SAT_OFF_HOURS_REFRESH_SECONDS >= settings.SAT_HEARTBEAT_INTERVAL_SECONDS
    assert settings.CELERY_BEAT_MAX_LOOP_INTERVAL > 0


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
