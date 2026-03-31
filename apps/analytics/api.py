"""Django Ninja API endpoints for analytics."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from ninja import Router

from apps.analytics.schemas import DailyReportResponse
from apps.analytics.services import get_daily_report, get_recent_reports
from common.exceptions import NotFoundError
from common.pagination import StandardPagination, paginate

if TYPE_CHECKING:
    from apps.analytics.models import DailyReport

router = Router()


@router.get("/reports/", response=list[DailyReportResponse], summary="List recent daily reports")
@paginate(StandardPagination)
def list_reports(request, days: int = 30) -> list[DailyReport]:
    """Return paginated daily reports for the past N days (default 30)."""
    return get_recent_reports(days=days)


@router.get("/reports/{report_date}", response=DailyReportResponse, summary="Get daily report by date")
def get_report(request, report_date: date) -> DailyReport:
    """Return a single daily report for the given date."""
    report = get_daily_report(report_date)
    if report is None:
        raise NotFoundError(f"No report found for {report_date}.")
    return report
