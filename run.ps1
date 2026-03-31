param(
    [Parameter(Position=0)]
    [string]$Target = "help"
)

switch ($Target) {
    "run" {
        uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload
    }
    "test" {
        pytest --cov=apps --cov=common --cov-report=html --cov-report=term-missing
    }
    "lint" {
        ruff check . --fix
        ruff format .
    }
    "lint-check" {
        ruff check .
        ruff format --check .
    }
    "migrate" {
        python manage.py migrate
    }
    "migrations" {
        python manage.py makemigrations
    }
    "shell" {
        python manage.py shell_plus --ipython
    }
    "superuser" {
        python manage.py createsuperuser
    }
    "docker-up" {
        docker-compose up -d
    }
    "docker-down" {
        docker-compose down
    }
    "docker-build" {
        docker-compose build
    }
    "docker-logs" {
        docker-compose logs -f
    }
    "celery" {
        celery -A core.celery worker --loglevel=info
    }
    "celery-beat" {
        celery -A core.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    }
    "help" {
        Write-Host ""
        Write-Host "JUDAH — Available commands (.\run.ps1 <target>):"
        Write-Host ""
        Write-Host "  run           Start Uvicorn dev server on :8000"
        Write-Host "  test          Run pytest with coverage"
        Write-Host "  lint          Ruff check + format (with auto-fix)"
        Write-Host "  lint-check    Ruff check (no fix, for CI)"
        Write-Host "  migrate       Apply database migrations"
        Write-Host "  migrations    Generate new migration files"
        Write-Host "  shell         Open Django shell (IPython)"
        Write-Host "  superuser     Create a Django superuser"
        Write-Host "  docker-up     Start all Docker services"
        Write-Host "  docker-down   Stop all Docker services"
        Write-Host "  docker-build  Rebuild Docker images"
        Write-Host "  docker-logs   Tail Docker service logs"
        Write-Host "  celery        Start Celery worker"
        Write-Host "  celery-beat   Start Celery Beat scheduler"
        Write-Host ""
    }
    default {
        Write-Error "Unknown target: '$Target'. Run '.\run.ps1 help' for available targets."
        exit 1
    }
}
