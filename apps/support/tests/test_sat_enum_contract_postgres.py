"""PostgreSQL contract tests for the legacy SAT status enum."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection, transaction
from django.test import override_settings

from apps.support.models import Agent, AgentAvailabilityDecision, AgentStatusHistory
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


def _agent(*, status: str) -> Agent:
    return Agent.objects.create(
        name="SAT Enum Contract Agent",
        agent_email="sat.enum.contract@example.com",
        hubspot_owner_id=48108294672,
        status_enum=status,
        auto_assign_enabled=True,
        is_active=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
    )


def _available_hubspot_user() -> dict[str, str]:
    return {
        "user_id": "48108294672",
        "email": "sat.enum.contract@example.com",
        "availability_status": "available",
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
    mock_client_factory.return_value.get_all_owners_availability.return_value = [_available_hubspot_user()]

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
