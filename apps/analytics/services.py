"""Business logic for analytics aggregation."""

from datetime import date, timedelta

import structlog

from apps.analytics.models import DailyReport

logger = structlog.get_logger(__name__)


def get_daily_report(report_date: date) -> DailyReport | None:
    """Fetch a pre-computed daily report for the given date.

    Args:
        report_date: The target date.

    Returns:
        DailyReport instance or None if not yet generated.
    """
    try:
        return DailyReport.objects.get(date=report_date)
    except DailyReport.DoesNotExist:
        return None


def get_recent_reports(days: int = 30) -> list[DailyReport]:
    """Return the most recent N days of daily reports.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        List of DailyReport instances ordered by date descending.
    """
    start_date = date.today() - timedelta(days=days)
    return list(DailyReport.objects.filter(date__gte=start_date).order_by("-date"))


def compute_daily_report(report_date: date) -> DailyReport:
    """Compute and persist a daily report for the given date.

    This function aggregates data from the support app.

    Args:
        report_date: Date to aggregate data for.

    Returns:
        Created or updated DailyReport instance.
    """
    from apps.support.models import Ticket

    day_start = report_date
    day_end = report_date + timedelta(days=1)

    opened = Ticket.objects.filter(created_at__date=day_start).count()
    resolved = Ticket.objects.filter(
        resolved_at__date=day_start,
        status=Ticket.Status.RESOLVED,
    ).count()
    escalated = Ticket.objects.filter(
        created_at__date=day_start,
        sla_breached=True,
    ).count()

    report, _ = DailyReport.objects.update_or_create(
        date=report_date,
        defaults={
            "total_tickets_opened": opened,
            "total_tickets_resolved": resolved,
            "total_tickets_escalated": escalated,
        },
    )
    logger.info("daily_report_computed", date=str(report_date), opened=opened, resolved=resolved)
    return report
