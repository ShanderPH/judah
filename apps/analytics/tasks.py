"""Celery tasks for analytics aggregation."""

from datetime import date, timedelta

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def generate_daily_report(self, report_date_str: str | None = None) -> dict:
    """Generate or regenerate a daily analytics report.

    Args:
        report_date_str: ISO date string (YYYY-MM-DD). Defaults to yesterday.

    Returns:
        Dict with report_date and status.
    """
    from apps.analytics.services import compute_daily_report

    target_date = (
        date.fromisoformat(report_date_str) if report_date_str else date.today() - timedelta(days=1)
    )

    try:
        report = compute_daily_report(target_date)
        logger.info("daily_report_task_success", date=str(target_date), report_id=report.pk)
        return {"report_date": str(target_date), "status": "success", "report_id": report.pk}
    except Exception as exc:
        logger.error("daily_report_task_failed", date=str(target_date), error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def backfill_reports(self, days: int = 7) -> dict:
    """Backfill daily reports for the past N days.

    Args:
        days: Number of past days to backfill (default 7).

    Returns:
        Dict with count of reports generated.
    """
    from apps.analytics.services import compute_daily_report

    count = 0
    for i in range(1, days + 1):
        target = date.today() - timedelta(days=i)
        try:
            compute_daily_report(target)
            count += 1
        except Exception as exc:
            logger.error("backfill_report_failed", date=str(target), error=str(exc))

    logger.info("backfill_complete", days=days, count=count)
    return {"days_requested": days, "reports_generated": count}
