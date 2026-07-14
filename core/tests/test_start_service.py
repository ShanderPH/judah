"""Tests for the production service launcher."""

from unittest.mock import Mock

from scripts import start_service


def test_render_defaults_to_bundled_worker(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("RUN_CELERY_IN_WEB", raising=False)
    migrate = Mock()
    supervised = Mock(return_value=0)
    monkeypatch.setattr(start_service, "run_migrations", migrate)
    monkeypatch.setattr(start_service, "run_supervised", supervised)

    assert start_service.main() == 0
    migrate.assert_called_once_with()
    supervised.assert_called_once_with()


def test_explicit_flag_can_disable_bundled_worker(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RUN_CELERY_IN_WEB", "false")
    monkeypatch.setattr(start_service, "run_migrations", Mock())
    monkeypatch.setattr(start_service, "web_command", Mock(return_value=["gunicorn", "app"]))
    exec_process = Mock()
    monkeypatch.setattr(start_service.os, "execvp", exec_process)

    assert start_service.main() == 1
    exec_process.assert_called_once_with("gunicorn", ["gunicorn", "app"])


def test_bundled_worker_consumes_default_and_ai_queues(monkeypatch) -> None:
    monkeypatch.delenv("CELERY_WEB_CONCURRENCY", raising=False)

    command = start_service.worker_command()

    assert "--beat" in command
    assert "--pool=solo" in command
    assert "--concurrency=1" in command
    assert "--queues=celery,ai_tasks" in command


def test_bundled_web_uses_single_worker_by_default(monkeypatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("PORT", "10000")

    command = start_service.web_command(bundled_worker=True)

    assert "0.0.0.0:10000" in command
    assert command[command.index("--workers") + 1] == "1"


def test_supervisor_exits_when_celery_stops(monkeypatch) -> None:
    worker = Mock()
    worker.poll.return_value = 7
    web = Mock()
    web.poll.return_value = None
    monkeypatch.setattr(start_service.subprocess, "Popen", Mock(side_effect=[worker, web]))
    monkeypatch.setattr(start_service.signal, "signal", Mock())
    stop_processes = Mock()
    monkeypatch.setattr(start_service, "_stop_processes", stop_processes)

    assert start_service.run_supervised() == 7
    stop_processes.assert_called_once_with([worker, web])
