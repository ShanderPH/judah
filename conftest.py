"""Root pytest configuration — database isolation for Supabase-backed tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def django_db_setup():
    """Skip Django's default create/destroy test database lifecycle.

    Tests connect to the existing database configured in ``core.settings.test``
    (Supabase for local dev, a transient PostgreSQL for CI). Django wraps each
    test in a transaction that is rolled back after the test, so production data
    is never modified permanently.
    """


@pytest.fixture(autouse=True)
def isolate_db(db):
    """Delete all pre-existing rows from tables used by tests before each test.

    This prevents production data (real agents, conversations, logs) from
    contaminating assertions about counts and query results.
    Each test runs inside a transaction that is rolled back afterward, so this
    deletion is invisible to the production database.
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
