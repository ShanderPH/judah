"""Root pytest configuration — database isolation and safe local testing."""

from __future__ import annotations

import os

import pytest

from common.database_safety import assert_safe_test_database

assert_safe_test_database(os.environ.get("DATABASE_URL", ""))


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Configure the test database lifecycle depending on the backend.

    For local SQLite runs (the default via ``run_tests_local.py``), pytest-django
    creates a fresh test database file and this fixture applies migrations so the
    schema is present before any test runs.

    For PostgreSQL CI runs, pytest-django's dependency above creates and migrates
    a separate ``test_`` database. The module-level safety assertion rejects
    remote hosts and non-disposable database names before setup can begin.
    """
    from django.db import connections

    connection = connections["default"]
    if connection.vendor == "sqlite":
        with django_db_blocker.unblock():
            from django.core.management import call_command

            call_command("migrate", "--run-syncdb", verbosity=0)
        return

    # PostgreSQL setup and teardown are owned by pytest-django.


@pytest.fixture(autouse=True)
def isolate_db(db):
    """Delete pre-existing rows from tables used by tests before each test.

    This prevents production data (real agents, conversations, logs) from
    contaminating assertions about counts and query results. Each test runs
    inside a transaction that is rolled back afterward, so this deletion is
    invisible to the production database.
    """
    from apps.support.models import (
        Agent,
        AgentMetrics,
        AgentStatusHistory,
        AssignedConversation,
        AssignmentLog,
        ClosedConversation,
        ConversationReassignment,
        NewConversation,
    )

    # Delete in FK-safe order: dependents first, then parent tables.
    # agent_metrics has a DB-level FK on agents.hubspot_owner_id, so it must
    # be cleared before agents. agent_status_history has FK on agents too.
    ConversationReassignment.objects.all().delete()
    AssignedConversation.objects.all().delete()
    ClosedConversation.objects.all().delete()
    NewConversation.objects.all().delete()
    AssignmentLog.objects.all().delete()
    AgentMetrics.objects.all().delete()
    AgentStatusHistory.objects.all().delete()
    Agent.objects.all().delete()
