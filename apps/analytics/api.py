"""Django Ninja API endpoints for analytics."""

from datetime import date

from ninja import Router

from apps.analytics.models import DailyReport
from apps.analytics.schemas import DailyReportResponse
from apps.analytics.services import get_daily_report, get_recent_reports
from common.exceptions import NotFoundError
from common.pagination import StandardPagination, paginate

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
