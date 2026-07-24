"""Start Judah safely on both dedicated and single-service deployments."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

_TRUTHY = {"1", "true", "yes", "on"}


def env_flag(name: str, *, default: bool = False) -> bool:
    """Read a conventional boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY


def web_command(*, bundled_worker: bool) -> list[str]:
    """Build the Gunicorn command without relying on shell expansion."""
    default_workers = "1" if bundled_worker else "2"
    return [
        "gunicorn",
        "core.asgi:application",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "--bind",
        f"0.0.0.0:{os.getenv('PORT', '8000')}",
        "--workers",
        os.getenv("WEB_CONCURRENCY", default_workers),
        "--worker-connections",
        "1000",
        "--timeout",
        "120",
        "--keep-alive",
        "5",
        "--log-level",
        "info",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
    ]


def worker_command() -> list[str]:
    """Build a low-memory Celery worker with embedded beat for Render Free."""
    return [
        "celery",
        "-A",
        "core",
        "worker",
        "--beat",
        "--loglevel=info",
        "--pool=solo",
        f"--concurrency={os.getenv('CELERY_WEB_CONCURRENCY', '1')}",
        "--queues=celery,ai_tasks",
        "--scheduler=django_celery_beat.schedulers:DatabaseScheduler",
    ]


def run_migrations() -> None:
    """Apply pending migrations before any process can consume webhooks."""
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)


def _stop_processes(processes: Sequence[subprocess.Popen], *, timeout: float = 20.0) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.monotonic() + timeout
    for process in processes:
        if process.poll() is not None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_supervised() -> int:
    """Run Celery and Gunicorn together, failing if either process exits."""
    processes = [
        subprocess.Popen(worker_command()),
        subprocess.Popen(web_command(bundled_worker=True)),
    ]
    stopping = False

    def request_shutdown(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        _stop_processes(processes)

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    try:
        while not stopping:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code or 1
            time.sleep(0.5)
        return 0
    finally:
        _stop_processes(processes)


def main() -> int:
    run_migrations()

    # Render exposes RENDER=true automatically. An explicit value always wins,
    # allowing paid Render deployments with dedicated workers to opt out.
    bundled_worker = env_flag("RUN_CELERY_IN_WEB", default=env_flag("RENDER"))
    if bundled_worker:
        return run_supervised()

    command = web_command(bundled_worker=False)
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
