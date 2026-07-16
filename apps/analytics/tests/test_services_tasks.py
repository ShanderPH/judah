"""Tests for analytics services and Celery tasks."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.analytics.models import DailyReport
from apps.analytics.services import compute_daily_report, get_daily_report, get_recent_reports
from apps.analytics.tasks import backfill_reports, generate_daily_report


@pytest.mark.django_db
def test_daily_report_queries_and_recent_ordering() -> None:
    older = DailyReport.objects.create(date=date(2026, 7, 14))
    newer = DailyReport.objects.create(date=date(2026, 7, 15))

    assert get_daily_report(newer.date) == newer
    assert get_daily_report(date(2020, 1, 1)) is None
    assert get_recent_reports(days=10)[:2] == [newer, older]


def test_compute_daily_report_aggregates_ticket_counts() -> None:
    opened_qs = Mock()
    opened_qs.count.return_value = 4
    resolved_qs = Mock()
    resolved_qs.count.return_value = 3
    report = SimpleNamespace(pk=1)

    with (
        patch("apps.support.models.Ticket.objects.filter", side_effect=[opened_qs, resolved_qs]),
        patch("apps.analytics.services.DailyReport.objects.update_or_create", return_value=(report, True)) as update,
    ):
        assert compute_daily_report(date(2026, 7, 15)) is report

    update.assert_called_once_with(
        date=date(2026, 7, 15),
        defaults={
            "total_tickets_opened": 4,
            "total_tickets_resolved": 3,
            "total_tickets_escalated": 0,
        },
    )


def test_generate_daily_report_success_and_retry() -> None:
    report = SimpleNamespace(pk=9)
    with patch("apps.analytics.services.compute_daily_report", return_value=report):
        result = generate_daily_report.run("2026-07-15")
    assert result == {"report_date": "2026-07-15", "status": "success", "report_id": 9}

    with (
        patch("apps.analytics.services.compute_daily_report", side_effect=RuntimeError("db")),
        patch.object(generate_daily_report, "retry", side_effect=RuntimeError("retried")) as retry,
        pytest.raises(RuntimeError, match="retried"),
    ):
        generate_daily_report.run("2026-07-15")
    retry.assert_called_once()


def test_backfill_reports_counts_successes_and_continues_after_failure() -> None:
    with patch(
        "apps.analytics.services.compute_daily_report",
        side_effect=[SimpleNamespace(), RuntimeError("one day failed"), SimpleNamespace()],
    ):
        assert backfill_reports.run(days=3) == {"days_requested": 3, "reports_generated": 2}
