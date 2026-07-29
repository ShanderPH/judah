"""Tests for safe support-agent provisioning."""

from __future__ import annotations

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.support.models import Agent

pytestmark = pytest.mark.django_db


def _create_user() -> object:
    return get_user_model().objects.create_user(
        username="suporte_inchurch",
        email="support-agent@example.test",
        first_name="Suporte",
        last_name="inChurch",
    )


def test_provision_support_agent_is_dry_run_by_default() -> None:
    user = _create_user()
    stdout = StringIO()

    call_command(
        "provision_support_agent",
        username=user.username,
        hubspot_owner_id=81908844,
        stdout=stdout,
    )

    user.refresh_from_db()
    assert user.hubspot_owner_id == ""
    assert not Agent.objects.exists()
    assert "No database changes were made." in stdout.getvalue()


def test_provision_support_agent_atomically_links_user_and_agent() -> None:
    user = _create_user()

    call_command(
        "provision_support_agent",
        username=user.username,
        hubspot_owner_id=81908844,
        execute=True,
        stdout=StringIO(),
    )

    user.refresh_from_db()
    agent = Agent.objects.get(hubspot_owner_id=81908844)
    assert user.hubspot_owner_id == "81908844"
    assert user.role == user.Role.VIEWER
    assert agent.name == "Suporte inChurch"
    assert agent.agent_email == user.email
    assert agent.status_enum == Agent.StatusEnum.OFFLINE
    assert agent.is_active is True
    assert agent.auto_assign_enabled is True


def test_provision_support_agent_execute_is_idempotent() -> None:
    user = _create_user()

    for _attempt in range(2):
        call_command(
            "provision_support_agent",
            username=user.username,
            hubspot_owner_id=81908844,
            execute=True,
            stdout=StringIO(),
        )

    assert Agent.objects.filter(hubspot_owner_id=81908844).count() == 1


def test_provision_support_agent_fails_closed_on_owner_conflict() -> None:
    user = _create_user()
    Agent.objects.create(
        name="Another agent",
        agent_email="another-agent@example.test",
        hubspot_owner_id=81908844,
    )

    with pytest.raises(CommandError, match="different support-agent email"):
        call_command(
            "provision_support_agent",
            username=user.username,
            hubspot_owner_id=81908844,
            execute=True,
            stdout=StringIO(),
        )

    user.refresh_from_db()
    assert user.hubspot_owner_id == ""
