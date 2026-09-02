"""Real Celery/Redis/PostgreSQL integration coverage for assignment fencing."""

from __future__ import annotations

import os
import secrets
import threading
from unittest.mock import MagicMock, patch

import pytest
from celery.contrib.testing.worker import start_worker
from django.db import close_old_connections
from django.utils import timezone

from apps.support.models import Agent, AssignmentAttempt, AvailabilityReconciliationLease, NewConversation
from celery import Celery

REDIS_TEST_URL = os.environ.get("JUDAH_TEST_REDIS_URL", "")
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.skipif(not REDIS_TEST_URL, reason="JUDAH_TEST_REDIS_URL is required"),
]


def _redis_database_url(database: int) -> str:
    return f"{REDIS_TEST_URL.rsplit('/', maxsplit=1)[0]}/{database}"


def _agent(*, email: str, owner_id: int, max_chats: int) -> Agent:
    now = timezone.now()
    return Agent.objects.create(
        name=f"V03 Agent {owner_id}",
        agent_email=email,
        hubspot_owner_id=owner_id,
        hubspot_user_id=str(owner_id),
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
        auto_assign_enabled=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=max_chats,
        availability_observed_at=now,
        eligibility_state=Agent.EligibilityState.ELIGIBLE,
        eligibility_reason="eligible",
        availability_revision=1,
    )


def test_real_worker_serializes_sat_and_respects_capacity() -> None:
    """Exercise a non-eager threaded worker through a disposable Redis broker."""
    token = secrets.token_hex(6)
    queue_name = f"judah-v03-{token}"
    celery_app = Celery(
        f"judah-v03-{token}",
        broker=_redis_database_url(14),
        backend=_redis_database_url(15),
    )
    celery_app.conf.update(
        task_always_eager=False,
        task_ignore_result=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_default_queue=queue_name,
        worker_prefetch_multiplier=1,
        result_expires=60,
    )

    @celery_app.task(name=f"tests.v03.sat.{token}", acks_late=True)
    def run_sat() -> dict:
        close_old_connections()
        try:
            from apps.support.sat_service import sat_heartbeat

            return sat_heartbeat(task_id=f"worker-{token}")
        finally:
            close_old_connections()

    @celery_app.task(name=f"tests.v03.reserve.{token}", acks_late=True)
    def reserve(ticket_id: str) -> str:
        close_old_connections()
        try:
            from apps.support.durable_assignment_service import reserve_next_assignment

            candidates = [
                (agent, "eligible")
                for agent in Agent.objects.filter(agent_email__startswith="v03-reserve-").order_by("pk")
            ]
            with patch(
                "apps.support.durable_assignment_service._verify_candidates",
                return_value=candidates,
            ):
                return reserve_next_assignment(ticket_id).reason
        finally:
            close_old_connections()

    sat_agent = _agent(email="v03-sat@example.test", owner_id=8100, max_chats=1)
    provider = MagicMock()
    provider_started = threading.Event()
    release_provider = threading.Event()

    def delayed_availability(*, force_refresh: bool = False) -> list[dict[str, str]]:
        provider_started.set()
        assert release_provider.wait(timeout=10)
        return [{"email": sat_agent.agent_email, "status_enum": "online"}]

    provider.get_all_owners_availability.side_effect = delayed_availability

    with (
        patch("apps.support.sat_service.is_business_hours", return_value=True),
        patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=provider),
        start_worker(
            celery_app,
            pool="threads",
            concurrency=4,
            perform_ping_check=False,
            shutdown_timeout=15,
        ),
    ):
        first_sat = run_sat.apply_async(queue=queue_name)
        assert provider_started.wait(timeout=10)
        second_sat = run_sat.apply_async(queue=queue_name)
        second_result = second_sat.get(timeout=10)
        release_provider.set()
        first_result = first_sat.get(timeout=10)

        assert first_result["agents_checked"] == 1
        assert second_result["skipped_locked"] is True
        assert provider.get_all_owners_availability.call_count == 1
        assert run_sat.acks_late is True

        _agent(email="v03-reserve-a@example.test", owner_id=8201, max_chats=4)
        _agent(email="v03-reserve-b@example.test", owner_id=8202, max_chats=4)
        ticket_ids = [f"v03-ticket-{index}" for index in range(8)]
        for ticket_id in ticket_ids:
            NewConversation.objects.create(
                hubspot_ticket_id=ticket_id,
                entered_queue_at=timezone.now(),
                automatic_assignment_eligible=True,
            )

        results = [reserve.apply_async(args=(ticket_id,), queue=queue_name) for ticket_id in ticket_ids]
        results.append(reserve.apply_async(args=(ticket_ids[0],), queue=queue_name))
        reasons = [result.get(timeout=15) for result in results]

    agents = list(Agent.objects.filter(agent_email__startswith="v03-reserve-").order_by("pk"))
    assert AssignmentAttempt.objects.filter(ticket_id__startswith="v03-ticket-").count() == 8
    assert sum(agent.current_simultaneous_chats for agent in agents) == 8
    assert all(0 <= agent.current_simultaneous_chats <= agent.max_simultaneous_chats for agent in agents)
    assert reasons.count("reserved") == 8
    assert reasons.count("queue_empty_or_claimed") == 1
    lease = AvailabilityReconciliationLease.objects.get(key="sat-authoritative-reconciliation")
    assert lease.generation == 1
    assert lease.owner_token == ""
