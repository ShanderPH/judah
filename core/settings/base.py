"""Base settings shared across all environments."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import structlog
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")

DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# --- Application definition ---

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "ninja",
    "ninja_jwt",
    "ninja_jwt.token_blacklist",
    "corsheaders",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.auth_user",
    "apps.church",
    "apps.knowledge",
    "apps.support",
    "apps.ai_agents",
    "apps.integrations",
    "apps.webhooks",
    "apps.analytics",
    "apps.health",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.RequestLoggingMiddleware",
    "common.rate_limit.RateLimitMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# --- Database ---

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
    }
}

_database_url = config("DATABASE_URL", default="")
if _database_url:
    import dj_database_url  # type: ignore[import-untyped]

    DATABASES["default"] = dj_database_url.parse(_database_url, conn_max_age=60)

# --- Auth ---

AUTH_USER_MODEL = "auth_user.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- JWT ---

NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("DJANGO_SECRET_KEY"),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- Cache (Redis) ---
# Uses Django's built-in redis backend (no django-redis dependency needed).
# Railway may provide REDIS_PRIVATE_URL or REDIS_URL depending on configuration.

REDIS_URL = config(
    "REDIS_URL",
    default=config("REDIS_PRIVATE_URL", default="redis://localhost:6379/0"),
)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry_on_timeout": True,
        },
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# --- Celery ---

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 600

# Dedicated queue for AI supervisor pipeline. Keeps long-running LLM
# workloads isolated from the latency-sensitive support / matchmaker
# queues so that a runaway agent cannot starve auto-assignment workers.
# The queue is declared here but ``run_supervisor_pipeline_task`` only
# dispatches when ``AI_ROUTING_ENABLED`` is true.
CELERY_TASK_ROUTES = {
    "ai_agents.run_supervisor_pipeline_task": {"queue": "ai_tasks"},
}

# --- Feature flags ---

# AI routing is disabled by default. When False, the ``/ai/`` Ninja router is
# not mounted and the supervisor pipeline task is not dispatched from webhooks.
# This isolates the dormant AI drop from the legacy auto-assignment system.
AI_ROUTING_ENABLED = config("AI_ROUTING_ENABLED", default=False, cast=bool)

from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Sync HubSpot N1 team members daily at 06:00 AM (São Paulo)
    "sync-hubspot-team-members-daily": {
        "task": "support.task_sync_hubspot_team_members",
        "schedule": crontab(hour=6, minute=0),
    },
    # Aggregate queue metrics daily at 00:05 AM (São Paulo)
    "aggregate-queue-metrics-daily": {
        "task": "support.task_aggregate_queue_metrics",
        "schedule": crontab(hour=0, minute=5),
    },
    # SAT heartbeat — sync agent availability every 20 seconds (skips off-hours)
    "sat-heartbeat": {
        "task": "support.task_sat_heartbeat",
        "schedule": 20,  # seconds
    },
    # SAT daily counter reset at midnight
    "sat-reset-daily-counters": {
        "task": "support.task_sat_reset_daily_counters",
        "schedule": crontab(hour=0, minute=1),
    },
    # Matchmaker safety net — drain pending queue every 60 seconds
    "matchmaker-drain-queue": {
        "task": "support.task_matchmaker_drain_queue",
        "schedule": 60,  # seconds
    },
    # Sync NOVO-stage tickets from HubSpot daily at 08:00 AM (São Paulo)
    "sync-novo-stage-tickets-daily": {
        "task": "support.task_sync_novo_stage_tickets",
        "schedule": crontab(hour=8, minute=0),
    },
    # Aggregate per-agent metrics daily at 00:10 AM (São Paulo)
    "aggregate-agent-metrics-daily": {
        "task": "support.task_aggregate_agent_metrics",
        "schedule": crontab(hour=0, minute=10),
    },
    # Reconcile agent chat counts with HubSpot every hour during business hours
    "reconcile-agent-counts-hourly": {
        "task": "support.task_reconcile_agent_counts",
        "schedule": crontab(minute=30),  # :30 of every hour
    },
}

# ---------------------------------------------------------------------------
# Auto-assignment configuration
# ---------------------------------------------------------------------------

HUBSPOT_N1_TEAM_ID = config("HUBSPOT_N1_TEAM_ID", default="8")

# --- Internationalization ---

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --- Static files ---
# STORAGES replaces deprecated STATICFILES_STORAGE (removed in Django 5.1).

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# --- Default primary key ---

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- CORS ---


def _normalize_cors_origins(origins_str: str) -> list[str]:
    """Ensure all CORS origins have a scheme (https://)."""
    origins = [o.strip() for o in origins_str.split(",") if o.strip()]
    normalized = []
    for origin in origins:
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        normalized.append(origin)
    return normalized


CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=_normalize_cors_origins,
)
CORS_ALLOW_CREDENTIALS = True

# --- Supabase ---

SUPABASE_URL = config("SUPABASE_URL", default="")
SUPABASE_SERVICE_KEY = config("SUPABASE_SERVICE_KEY", default="")

# --- External APIs ---

OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
PINECONE_API_KEY = config("PINECONE_API_KEY", default="")
PINECONE_INDEX_NAME = config("PINECONE_INDEX_NAME", default="inchurch-knowledge")
PINECONE_HOST = config("PINECONE_HOST", default="")

SALOMAO_V1_BASE_URL = config("SALOMAO_V1_BASE_URL", default="")
SALOMAO_V1_TIMEOUT_SECONDS = config("SALOMAO_V1_TIMEOUT_SECONDS", default=45.0, cast=float)
SALOMAO_V1_IMAGE_TIMEOUT_SECONDS = config("SALOMAO_V1_IMAGE_TIMEOUT_SECONDS", default=180.0, cast=float)
SALOMAO_V1_AS_TEAM_AGENT = config("SALOMAO_V1_AS_TEAM_AGENT", default=True, cast=bool)

HUBSPOT_ACCESS_TOKEN = config("HUBSPOT_ACCESS_TOKEN", default="")
HUBSPOT_APP_SECRET = config("HUBSPOT_APP_SECRET", default="")
HUBSPOT_SALOMAO_SENDER_ACTOR_ID = config("HUBSPOT_SALOMAO_SENDER_ACTOR_ID", default="")
HUBSPOT_AI_TRIAGE_STAGE_ID = config("HUBSPOT_AI_TRIAGE_STAGE_ID", default="")
HUBSPOT_AI_REPLY_DISABLED_CHANNELS = config("HUBSPOT_AI_REPLY_DISABLED_CHANNELS", default="")
HUBSPOT_SUPPORT_PIPELINE_ID = config("HUBSPOT_SUPPORT_PIPELINE_ID", default="636459134")
HUBSPOT_SUPPORT_NEW_STAGE_ID = config("HUBSPOT_SUPPORT_NEW_STAGE_ID", default="939275049")
HUBSPOT_SUPPORT_CLOSED_STAGE_ID = config("HUBSPOT_SUPPORT_CLOSED_STAGE_ID", default="939275052")
HUBSPOT_OFF_HOURS_PIPELINE_ID = config("HUBSPOT_OFF_HOURS_PIPELINE_ID", default="636594474")
HUBSPOT_OFF_HOURS_STAGE_ID = config("HUBSPOT_OFF_HOURS_STAGE_ID", default="1122729533")
HUBSPOT_DEFAULT_TICKET_PIPELINE_ID = config("HUBSPOT_DEFAULT_TICKET_PIPELINE_ID", default="0")
HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID = config("HUBSPOT_DEFAULT_TICKET_NEW_STAGE_ID", default="1")
HUBSPOT_DEFAULT_TICKET_OPEN_STAGE_ID = config("HUBSPOT_DEFAULT_TICKET_OPEN_STAGE_ID", default="2")
HUBSPOT_DEFAULT_TICKET_WAITING_STAGE_ID = config("HUBSPOT_DEFAULT_TICKET_WAITING_STAGE_ID", default="3")
HUBSPOT_DEFAULT_TICKET_CLOSED_STAGE_ID = config("HUBSPOT_DEFAULT_TICKET_CLOSED_STAGE_ID", default="4")
HUBSPOT_N2_PIPELINE_ID = config("HUBSPOT_N2_PIPELINE_ID", default="634240100")
HUBSPOT_N2_ENTRY_STAGE_ID = config("HUBSPOT_N2_ENTRY_STAGE_ID", default="936942376")
HUBSPOT_N2_CRITICAL_STAGE_ID = config("HUBSPOT_N2_CRITICAL_STAGE_ID", default="1060950860")
HUBSPOT_N2_HIGH_STAGE_ID = config("HUBSPOT_N2_HIGH_STAGE_ID", default="1060950861")
HUBSPOT_N2_MEDIUM_STAGE_ID = config("HUBSPOT_N2_MEDIUM_STAGE_ID", default="1060950862")
HUBSPOT_N2_LOW_STAGE_ID = config("HUBSPOT_N2_LOW_STAGE_ID", default="1060950863")
HUBSPOT_N2_TRIVIAL_STAGE_ID = config("HUBSPOT_N2_TRIVIAL_STAGE_ID", default="1060950864")
HUBSPOT_N2_RESOLVED_STAGE_ID = config("HUBSPOT_N2_RESOLVED_STAGE_ID", default="936942379")
HUBSPOT_TICKET_CHURCH_PROPERTY = config(
    "HUBSPOT_TICKET_CHURCH_PROPERTY",
    default="codigo_de_igreja_local___ticket",
)

JIRA_SERVER_URL = config("JIRA_SERVER_URL", default="")
JIRA_API_TOKEN = config("JIRA_API_TOKEN", default="")
JIRA_USER_EMAIL = config("JIRA_USER_EMAIL", default="")
JIRA_WEBHOOK_SECRET = config("JIRA_WEBHOOK_SECRET", default="")

# --- Sentry ---

SENTRY_DSN = config("SENTRY_DSN", default="")

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(monitor_beat_tasks=True),
            LoggingIntegration(level=None, event_level="ERROR"),
        ],
        traces_sample_rate=config("SENTRY_TRACES_SAMPLE_RATE", default=0.05, cast=float),
        profiles_sample_rate=config("SENTRY_PROFILES_SAMPLE_RATE", default=0.01, cast=float),
        send_default_pii=False,
        environment=os.environ.get("DJANGO_ENV", "development"),
        release=config("GIT_SHA", default=""),
    )

# ---------------------------------------------------------------------------
# Logging (structlog 24.x)
#
# Architecture:
#   structlog native records  →  _STRUCTLOG_PRE_CHAIN  →  wrap_for_formatter
#   stdlib/third-party records → foreign_pre_chain (same chain)  →  formatter
#   Both paths converge in ProcessorFormatter which applies the final renderer.
#
# In production:  JSONRenderer  → machine-readable, aggregator-friendly
# In development: ConsoleRenderer → human-readable coloured output (see development.py)
# ---------------------------------------------------------------------------

_STRUCTLOG_PRE_CHAIN: list = [
    # Merge any context variables bound via structlog.contextvars.bind_contextvars()
    structlog.contextvars.merge_contextvars,
    # Add log level name ("info", "error", …) to the event dict
    structlog.stdlib.add_log_level,
    # Add the logger name for easy filtering
    structlog.stdlib.add_logger_name,
    # ISO-8601 timestamp with UTC offset
    structlog.processors.TimeStamper(fmt="iso"),
    # Render stack info (for logger.exception / exc_info=True)
    structlog.processors.StackInfoRenderer(),
]

# Determine active log format from environment (base.py is loaded before
# production.py overrides DEBUG, so we read DJANGO_ENV directly).
_DJANGO_ENV = os.environ.get("DJANGO_ENV", "development")
_IS_PRODUCTION = _DJANGO_ENV == "production"

LOGGING: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    # ------------------------------------------------------------------ #
    # Formatters                                                           #
    # ------------------------------------------------------------------ #
    "formatters": {
        # JSON — used in staging/production for log aggregators
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            "foreign_pre_chain": _STRUCTLOG_PRE_CHAIN,
        },
        # Console — coloured human-readable (development only)
        "console": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True, sort_keys=False),
            ],
            "foreign_pre_chain": _STRUCTLOG_PRE_CHAIN,
        },
    },
    # ------------------------------------------------------------------ #
    # Filters                                                              #
    # ------------------------------------------------------------------ #
    "filters": {
        "suppress_health_checks": {
            "()": "common.logging.HealthCheckFilter",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            # Production uses JSON; development.py switches this to "console"
            "formatter": "json" if _IS_PRODUCTION else "console",
            "filters": ["suppress_health_checks"],
        },
    },
    # ------------------------------------------------------------------ #
    # Root logger (catch-all for unregistered loggers)                    #
    # ------------------------------------------------------------------ #
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    # ------------------------------------------------------------------ #
    # Per-logger configuration                                             #
    # ------------------------------------------------------------------ #
    "loggers": {
        # Django internals — INFO and above
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # DB query log — WARNING by default; set to DEBUG to capture all queries
        # (SlowQueryFilter in development.py limits output to slow queries only)
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Django security framework warnings
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Unhandled-exception logger — Django emits ERROR with traceback here
        # for any uncaught view exception. Keep it explicit so production never
        # silently swallows 500s when other "django" loggers raise their level.
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Application code
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "common": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        # Celery workers and beat
        "celery": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "celery.task": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Third-party HTTP clients — suppress verbose connection-level logs
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "urllib3": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# structlog global configuration
#
# The processor chain here applies to *structlog-native* log calls
# (logger.info(), logger.error(), etc.).  The final processor
# `wrap_for_formatter` hands the event dict off to ProcessorFormatter,
# which applies the renderer (JSONRenderer or ConsoleRenderer).
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        *_STRUCTLOG_PRE_CHAIN,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.ExceptionRenderer(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
