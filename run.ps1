param(
    [Parameter(Position=0)]
    [string]$Target = "help"
)

function Import-LocalEnv {
    $envFiles = @(".env", ".env.local")

    foreach ($envFile in $envFiles) {
        if (-not (Test-Path -LiteralPath $envFile)) {
            continue
        }

        Get-Content -LiteralPath $envFile | ForEach-Object {
            $line = $_.Trim()

            if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
                return
            }

            $key, $value = $line.Split("=", 2)
            $key = $key.Trim()
            $value = $value.Trim()

            if (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            ) {
                $value = $value.Substring(1, $value.Length - 2)
            }

            if ($key) {
                Set-Item -Path "Env:$key" -Value $value
            }
        }
    }
}

function Invoke-WithLocalEnv {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock
    )

    Import-LocalEnv
    & $ScriptBlock
}

switch ($Target) {
    "run" {
        Invoke-WithLocalEnv { uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload }
    }
    "agentos" {
        Invoke-WithLocalEnv { uvicorn apps.ai_agents.agent_os:app --host 0.0.0.0 --port 7777 --reload }
    }
    "test" {
        Invoke-WithLocalEnv { pytest --cov=apps --cov=common --cov-report=html --cov-report=term-missing }
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
        Invoke-WithLocalEnv { python manage.py migrate }
    }
    "migrations" {
        Invoke-WithLocalEnv { python manage.py makemigrations }
    }
    "shell" {
        Invoke-WithLocalEnv { python manage.py shell_plus --ipython }
    }
    "superuser" {
        Invoke-WithLocalEnv { python manage.py createsuperuser }
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
        Invoke-WithLocalEnv { celery -A core.celery worker --loglevel=info }
    }
    "celery-beat" {
        Invoke-WithLocalEnv { celery -A core.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler }
    }
    "help" {
        Write-Host ""
        Write-Host "JUDAH - Available commands (.\run.ps1 <target>):"
        Write-Host ""
        Write-Host "  run           Start Uvicorn dev server on :8000"
        Write-Host "  agentos       Start Agno AgentOS on :7777"
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
