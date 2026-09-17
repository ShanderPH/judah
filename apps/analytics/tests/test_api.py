"""Direct HTTP authorization and response contracts for analytics."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from ninja_jwt.tokens import AccessToken

from apps.analytics.models import DailyReport
from apps.analytics.schemas import DailyReportResponse
from apps.auth_user.models import User


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role,status", [(None, 401), ("viewer", 403), ("agent", 403), ("manager", 200), ("admin", 200)]
)
@pytest.mark.parametrize("detail", [False, True])
def test_report_authorization(client: Client, role: str | None, status: int, detail: bool) -> None:
    """Enforce roles on both routes while preserving serialization and pagination."""
    today = date.today()
    report = DailyReport.objects.create(date=today, total_tickets_opened=7)
    DailyReport.objects.create(date=today - timedelta(days=1))
    headers = {}
    if role:
        user = User.objects.create_user(username=f"report-{role}", role=role)
        headers["HTTP_AUTHORIZATION"] = f"Bearer {AccessToken.for_user(user)}"
    path = f"/api/v1/analytics/reports/{today}" if detail else "/api/v1/analytics/reports/?limit=1&offset=0"
    response = client.get(path, **headers)
    assert response.status_code == status, response.content
    if status == 200:
        expected = DailyReportResponse.model_validate(report).model_dump(mode="json")
        assert response.json() == (expected if detail else {"items": [expected], "count": 2})


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["viewer", "agent"])
@pytest.mark.parametrize("detail", [False, True])
def test_denied_reports_do_not_query_service(client: Client, role: str, detail: bool) -> None:
    """Reject before accessing either reporting service."""
    user = User.objects.create_user(username=f"denied-{role}", role=role)
    target = "get_daily_report" if detail else "get_recent_reports"
    path = "/api/v1/analytics/reports/2026-09-17" if detail else "/api/v1/analytics/reports/"
    with patch(f"apps.analytics.api.{target}", return_value=None if detail else []) as service:
        response = client.get(path, HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    assert response.status_code == 403
    service.assert_not_called()
