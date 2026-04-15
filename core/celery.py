"""Celery application configuration for JUDAH."""

import os

import structlog
from celery.signals import worker_ready

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

logger = structlog.get_logger(__name__)

app = Celery("judah")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Run startup tasks when the Celery worker is ready.

    Syncs NOVO-stage tickets from HubSpot into the internal queue so that
    conversations that arrived while the worker was down are picked up
    immediately.
    """
    from apps.support.tasks import task_sync_novo_stage_tickets

    logger.info("worker_ready_startup_sync", action="dispatching NOVO-stage ticket sync")
    task_sync_novo_stage_tickets.delay()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:
    """Debug task to verify Celery is working."""
    print(f"Request: {self.request!r}")
