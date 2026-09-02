"""PostgreSQL contract tests for the legacy SAT status enum."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from django.db import close_old_connections, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.support.models import (
    Agent,
    AgentAvailabilityDecision,
    AgentStatusHistory,
    AvailabilityReconciliationLease,
)
from common.database_safety import assert_safe_test_database

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

_ENUM_TYPE = "agent_status_enum"
_EXPECTED_ENUM_VALUES = ("online", "away", "offline", "busy")


def _column_type() -> tuple[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod), type.typname
            FROM pg_attribute AS attribute
            JOIN pg_type AS type ON type.oid = attribute.atttypid
            WHERE attribute.attrelid = 'agents'::regclass
              AND attribute.attname = 'status_enum'
              AND NOT attribute.attisdropped
            """
        )
        row = cursor.fetchone()
    assert row is not None
    return str(row[0]), str(row[1])


def _enum_values() -> tuple[str, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT enum.enumlabel
            FROM pg_enum AS enum
            JOIN pg_type AS type ON type.oid = enum.enumtypid
            WHERE type.typname = %s
            ORDER BY enum.enumsortorder
            """,
            [_ENUM_TYPE],
        )
        return tuple(str(row[0]) for row in cursor.fetchall())


@pytest.fixture(scope="module", autouse=True)
def legacy_agent_status_enum(django_db_setup: None, django_db_blocker: pytest.DjangoDbBlocker) -> Iterator[None]:
    """Temporarily reproduce the production enum inside a disposable test DB."""
    del django_db_setup
    assert_safe_test_database(os.environ.get("DATABASE_URL", ""))

    with django_db_blocker.unblock():
        if connection.vendor != "postgresql":
            pytest.skip("The legacy status enum contract requires PostgreSQL 16.")

        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            server_version_num = int(cursor.fetchone()[0])
        assert server_version_num // 10000 == 16

        database_name = str(connection.settings_dict["NAME"])
        assert database_name.startswith("test_")
        original_format_type, original_udt_name = _column_type()
        assert original_udt_name == "varchar"

        with transaction.atomic():
            existing_values = _enum_values()
            if existing_values:
                assert existing_values == _EXPECTED_ENUM_VALUES
            else:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE TYPE agent_status_enum AS ENUM ('online', 'away', 'offline', 'busy')")
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE agents ALTER COLUMN status_enum DROP DEFAULT")
                cursor.execute(
                    """
                    ALTER TABLE agents
                    ALTER COLUMN status_enum TYPE agent_status_enum
                    USING status_enum::text::agent_status_enum
                    """
                )
                cursor.execute("ALTER TABLE agents ALTER COLUMN status_enum SET DEFAULT 'away'::agent_status_enum")

        try:
            assert _column_type() == (_ENUM_TYPE, _ENUM_TYPE)
            yield
        finally:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("ALTER TABLE agents ALTER COLUMN status_enum DROP DEFAULT")
                cursor.execute(
                    """
                    ALTER TABLE agents
                    ALTER COLUMN status_enum TYPE varchar(20)
                    USING status_enum::text::varchar(20)
                    """
                )
                cursor.execute("ALTER TABLE agents ALTER COLUMN status_enum SET DEFAULT 'away'::character varying")
                cursor.execute("DROP TYPE agent_status_enum")
            assert _column_type() == (original_format_type, original_udt_name)


def _agent(*, status: str, index: int = 0) -> Agent:
    return Agent.objects.create(
        name=f"SAT Enum Contract Agent {index}",
        agent_email=f"sat.enum.contract.{index}@example.com",
        hubspot_owner_id=48108294672 + index,
        status_enum=status,
        auto_assign_enabled=True,
        is_active=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
    )


def _hubspot_user(*, index: int = 0, availability: str = "available") -> dict[str, str]:
    return {
        "user_id": str(48108294672 + index),
        "email": f"sat.enum.contract.{index}@example.com",
        "availability_status": availability,
        "out_of_office_hours": "[]",
        "working_hours": json.dumps([{"days": "EVERY_DAY", "startMinute": 0, "endMinute": 1440}]),
        "timezone": "America/Sao_Paulo",
    }


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    AVAILABILITY_REQUIRED_SAMPLES=1,
    AVAILABILITY_STABLE_SECONDS=0,
)
@patch("apps.support.sat_service.is_business_hours", return_value=True)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
@patch("apps.support.tasks.task_matchmaker_drain_queue.delay")
def test_normal_heartbeat_commits_status_against_legacy_enum(
    mock_drain: MagicMock,
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
) -> None:
    assert _column_type() == (_ENUM_TYPE, _ENUM_TYPE)
    agent = _agent(status=Agent.StatusEnum.AWAY)
    mock_client_factory.return_value.get_all_owners_availability.return_value = [_hubspot_user()]

    from apps.support.sat_service import sat_heartbeat

    result = sat_heartbeat(task_id="enum-contract-normal")

    agent.refresh_from_db()
    assert result["status_changes"] == 1
    assert agent.status_enum == Agent.StatusEnum.ONLINE
    assert AgentStatusHistory.objects.filter(agent=agent, old_status="away", new_status="online").count() == 1
    assert AgentAvailabilityDecision.objects.filter(agent=agent, new_status="online").count() == 1
    mock_drain.assert_called_once_with()


@patch("apps.support.sat_service.is_business_hours", return_value=False)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
def test_off_hours_heartbeat_commits_status_against_legacy_enum(
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
) -> None:
    assert _column_type() == (_ENUM_TYPE, _ENUM_TYPE)
    agent = _agent(status=Agent.StatusEnum.ONLINE)

    from apps.support.sat_service import sat_heartbeat

    result = sat_heartbeat(task_id="enum-contract-off-hours")

    agent.refresh_from_db()
    assert result["status_changes"] == 1
    assert result["off_hours_materialized"] is True
    assert agent.status_enum == Agent.StatusEnum.AWAY
    assert AgentStatusHistory.objects.filter(agent=agent, old_status="online", new_status="away").count() == 1
    assert AgentAvailabilityDecision.objects.filter(agent=agent, new_status="away").count() == 1
    mock_client_factory.assert_not_called()


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    AVAILABILITY_REQUIRED_SAMPLES=1,
    AVAILABILITY_STABLE_SECONDS=0,
)
@patch("apps.support.sat_service.is_business_hours", return_value=True)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
def test_unchanged_status_does_not_issue_scalar_enum_write(
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
) -> None:
    agent = _agent(status=Agent.StatusEnum.AWAY)
    mock_client_factory.return_value.get_all_owners_availability.return_value = [_hubspot_user(availability="away")]

    from apps.support.sat_service import sat_heartbeat

    with CaptureQueriesContext(connection) as queries:
        result = sat_heartbeat(task_id="enum-contract-unchanged")

    assert result["status_changes"] == 0
    assert not any('UPDATE "agents" SET "status_enum"' in query["sql"] for query in queries)
    agent.refresh_from_db()
    assert agent.status_enum == Agent.StatusEnum.AWAY


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    AVAILABILITY_REQUIRED_SAMPLES=1,
    AVAILABILITY_STABLE_SECONDS=0,
)
@pytest.mark.parametrize("agent_count", [8, 50, 500])
@patch("apps.support.sat_service.is_business_hours", return_value=True)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
@patch("apps.support.tasks.task_matchmaker_drain_queue.delay")
def test_status_transition_query_and_time_budget(
    mock_drain: MagicMock,
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
    agent_count: int,
) -> None:
    for index in range(agent_count):
        _agent(status=Agent.StatusEnum.AWAY, index=index)
    mock_client_factory.return_value.get_all_owners_availability.return_value = [
        _hubspot_user(index=index) for index in range(agent_count)
    ]

    from apps.support.sat_service import sat_heartbeat

    started_at = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        result = sat_heartbeat(task_id=f"enum-contract-scale-{agent_count}")
    duration_seconds = time.perf_counter() - started_at

    scalar_status_writes = [query for query in queries if 'UPDATE "agents" SET "status_enum"' in query["sql"]]
    assert result["status_changes"] == agent_count
    assert len(scalar_status_writes) == agent_count
    assert len(queries) <= (3 * agent_count) + 40
    assert duration_seconds < 12
    assert Agent.objects.filter(status_enum=Agent.StatusEnum.ONLINE).count() == agent_count
    mock_drain.assert_called_once_with()


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    AVAILABILITY_REQUIRED_SAMPLES=1,
    AVAILABILITY_STABLE_SECONDS=0,
)
@patch("apps.support.sat_service.is_business_hours", return_value=True)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
@patch("apps.support.tasks.task_matchmaker_drain_queue.delay")
def test_failure_after_scalar_status_write_rolls_back_everything(
    mock_drain: MagicMock,
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
) -> None:
    agent = _agent(status=Agent.StatusEnum.AWAY)
    mock_client_factory.return_value.get_all_owners_availability.return_value = [_hubspot_user()]

    from apps.support.sat_service import sat_heartbeat

    with (
        patch.object(Agent.objects, "bulk_update", side_effect=RuntimeError("injected batch failure")),
        pytest.raises(RuntimeError, match="injected batch failure"),
    ):
        sat_heartbeat(task_id="enum-contract-rollback")

    agent.refresh_from_db()
    assert agent.status_enum == Agent.StatusEnum.AWAY
    assert agent.availability_revision == 0
    assert not AgentStatusHistory.objects.filter(agent=agent).exists()
    assert not AgentAvailabilityDecision.objects.filter(agent=agent).exists()
    mock_drain.assert_not_called()


def test_concurrent_lease_has_one_writer_and_monotonic_generation() -> None:
    from apps.support.sat_service import _acquire_reconciliation_lease, _release_reconciliation_lease

    AvailabilityReconciliationLease.objects.all().delete()
    barrier = threading.Barrier(2)

    def acquire_concurrently() -> tuple[str, int] | None:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return _acquire_reconciliation_lease()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: acquire_concurrently(), range(2)))

    acquired = [result for result in results if result is not None]
    assert len(acquired) == 1
    assert results.count(None) == 1
    owner_token, first_generation = acquired[0]
    assert _release_reconciliation_lease(owner_token) is True

    next_lease = _acquire_reconciliation_lease()
    assert next_lease is not None
    next_token, next_generation = next_lease
    assert next_generation == first_generation + 1
    assert _release_reconciliation_lease(next_token) is True


@override_settings(
    ABSENCE_SAFE_ELIGIBILITY_ENFORCED=True,
    AVAILABILITY_REQUIRED_SAMPLES=1,
    AVAILABILITY_STABLE_SECONDS=0,
)
@patch("apps.support.sat_service.is_business_hours", return_value=True)
@patch("apps.integrations.hubspot.client.get_hubspot_client")
def test_stale_fencing_token_cannot_write_agent(
    mock_client_factory: MagicMock,
    _mock_business_hours: MagicMock,
) -> None:
    agent = _agent(status=Agent.StatusEnum.AWAY)
    Agent.objects.filter(pk=agent.pk).update(availability_fencing_token=9999)
    mock_client_factory.return_value.get_all_owners_availability.return_value = [_hubspot_user()]

    from apps.support.sat_service import sat_heartbeat

    result = sat_heartbeat(task_id="enum-contract-stale-fence")

    agent.refresh_from_db()
    assert result["agents_checked"] == 0
    assert result["status_changes"] == 0
    assert agent.status_enum == Agent.StatusEnum.AWAY
    assert agent.availability_fencing_token == 9999
    assert not AgentStatusHistory.objects.filter(agent=agent).exists()
    assert not AgentAvailabilityDecision.objects.filter(agent=agent).exists()
