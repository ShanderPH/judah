from unittest.mock import patch

from apps.ai_agents.services.watchdog import WatchdogResult
from apps.ai_agents.tasks import run_lifecycle_watchdog_task


def test_watchdog_task_exposes_only_generic_lifecycle_result() -> None:
    result = WatchdogResult(scanned=3, marked_retryable=2, marked_terminal=1)
    with patch("apps.ai_agents.services.watchdog.run_lifecycle_watchdog", return_value=result):
        assert run_lifecycle_watchdog_task() == {
            "scanned": 3,
            "marked_retryable": 2,
            "marked_terminal": 1,
        }


def test_removed_pipeline_tasks_are_not_exported() -> None:
    from apps.ai_agents import tasks

    assert not hasattr(tasks, "run_supervisor_pipeline_task")
    assert not hasattr(tasks, "run_salomao_v1_thread_pipeline_task")
    assert not hasattr(tasks, "retry_failed_lifecycle_instances_task")
