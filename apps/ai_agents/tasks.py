"""Celery tasks for the preserved conversation lifecycle."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="ai_agents.run_lifecycle_watchdog_task")
def run_lifecycle_watchdog_task() -> dict[str, int]:
    """Detect stuck lifecycle instances without invoking an AI pipeline."""
    from apps.ai_agents.services.watchdog import run_lifecycle_watchdog

    result = run_lifecycle_watchdog()
    return {
        "scanned": result.scanned,
        "marked_retryable": result.marked_retryable,
        "marked_terminal": result.marked_terminal,
    }


__all__ = ["run_lifecycle_watchdog_task"]
