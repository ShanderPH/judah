"""Opt-in PostgreSQL/Redis gate with a real Celery consumer and retry."""

import os
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
from celery.contrib.testing.worker import start_worker
from django.db import connection
from django.test import override_settings

from apps.support.models import SupportTicketOccupancy
from apps.support.tests.test_manual_assignment_capacity import agent, ticket
from celery import Celery

pytestmark = pytest.mark.django_db(transaction=True)


def test_real_worker_retries_provider_failure_and_persists_once(settings):
    redis_url = os.environ.get("JUDAH_CAPACITY_REDIS_URL", "")
    if not redis_url or connection.vendor != "postgresql":
        pytest.skip("Set JUDAH_CAPACITY_REDIS_URL with a local Redis and use PostgreSQL")
    assert urlparse(redis_url).hostname in {"127.0.0.1", "localhost", "::1"}
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    target = agent(200)
    from apps.support.tasks import task_reconcile_ticket_capacity

    lane = f"capacity-test-{uuid.uuid4().hex}"
    worker_app = Celery(lane, broker=redis_url, backend=redis_url)
    worker_app.conf.update(
        task_always_eager=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_hijack_root_logger=False,
    )
    worker_app.finalize()
    task = worker_app.tasks[task_reconcile_ticket_capacity.name]
    try:
        with (
            override_settings(
                REDIS_URL=redis_url,
                CACHES={
                    "default": {
                        "BACKEND": "django.core.cache.backends.redis.RedisCache",
                        "LOCATION": redis_url,
                    }
                },
            ),
            patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
        ):
            provider.return_value.get_ticket_details.side_effect = [RuntimeError("transient"), ticket(200)]
            with start_worker(worker_app, perform_ping_check=False, pool="solo", queues=[lane], shutdown_timeout=10):
                result = task.apply_async(args=["cap-1"], queue=lane)
                assert result.get(timeout=25, disable_sync_subtasks=False) == "active"
            assert provider.return_value.get_ticket_details.call_count == 2
        target.refresh_from_db()
        assert target.current_simultaneous_chats == 1
        assert SupportTicketOccupancy.objects.count() == 1
    finally:
        worker_app.close()
