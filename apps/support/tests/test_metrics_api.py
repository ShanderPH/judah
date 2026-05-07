"""API tests for support metrics endpoints — date serialization.

Regression coverage for a production outage where ``metric_date`` and
``log_date`` were typed ``str`` in the response schemas but the model
returns ``datetime.date``. Pydantic v2 raised a ``ValidationError`` on
every row and the endpoints 500'd, breaking the dashboard, auto-assignment,
and metrics screens for any user logged into ``judah-admin``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.auth_user.models import User
from apps.support.models import Agent, AgentDailyTimeLog, QueuePerformanceMetrics


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture(autouse=True)
def _clean_users(db) -> None:
    User.objects.all().delete()


@pytest.fixture
def auth_user() -> User:
    return User.objects.create_user(
        username="metricsuser",
        email="metrics@example.com",
        password="MetricsPass1",
    )


@pytest.fixture
def access_token(client: Client, auth_user: User) -> str:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "metricsuser", "password": "MetricsPass1"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


@pytest.fixture
def agent(db) -> Agent:
    return Agent.objects.create(
        name="Test Agent",
        agent_email="agent@test.com",
        hubspot_owner_id=1234,
        status_enum="online",
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=True,
    )


@pytest.mark.django_db
class TestQueueMetricsEndpoint:
    """GET /api/v1/support/queue/metrics/."""

    def test_returns_200_and_iso_metric_date(
        self, client: Client, access_token: str
    ) -> None:
        today = timezone.localdate()
        QueuePerformanceMetrics.objects.create(
            metric_date=today,
            total_entered_queue=10,
            total_assigned=8,
            total_closed=5,
        )
        response = client.get(
            "/api/v1/support/queue/metrics/?days=7",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["metric_date"] == today.isoformat()

    def test_returns_200_with_empty_table(
        self, client: Client, access_token: str
    ) -> None:
        response = client.get(
            "/api/v1/support/queue/metrics/?days=7",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        assert response.status_code == 200
        assert response.json() == {"items": [], "count": 0}


@pytest.mark.django_db
class TestTimeLogsEndpoint:
    """GET /api/v1/support/time-logs/."""

    def test_returns_200_and_iso_log_date(
        self, client: Client, access_token: str, agent: Agent
    ) -> None:
        today = timezone.localdate()
        AgentDailyTimeLog.objects.create(
            agent=agent,
            log_date=today,
            online_time_seconds=3600,
            away_time_seconds=600,
            status_transitions=4,
        )
        AgentDailyTimeLog.objects.create(
            agent=agent,
            log_date=today - timedelta(days=1),
            online_time_seconds=7200,
            away_time_seconds=1200,
            status_transitions=10,
        )
        response = client.get(
            "/api/v1/support/time-logs/?days=14",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["count"] == 2
        for item in body["items"]:
            assert isinstance(item["log_date"], str)
            assert len(item["log_date"]) == 10  # YYYY-MM-DD
