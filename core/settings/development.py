"""Development settings."""

from .base import *

DEBUG = True

INSTALLED_APPS = [
    *INSTALLED_APPS,
    "debug_toolbar",
    "django_extensions",
]

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    *MIDDLEWARE,
]

INTERNAL_IPS = ["127.0.0.1", "localhost"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Local development may ingest only when explicitly configured as the
# authoritative environment, but automatic owner mutation remains opt-in.
AUTO_ASSIGNMENT_ENABLED = config("AUTO_ASSIGNMENT_ENABLED", default=False, cast=bool)

# ---------------------------------------------------------------------------
# Logging overrides for development
# ---------------------------------------------------------------------------
# base.py already selected "console" formatter for local development,
# so no formatter override is needed here.
#
# Enable slow-query capture: log all queries that take ≥ 50 ms so you can
# spot N+1 problems and missing indexes during local development.

LOGGING["filters"]["slow_queries"] = {  # type: ignore[index]
    "()": "common.logging.SlowQueryFilter",
    "threshold_ms": 50.0,
}

# Route DB queries through the slow-query filter on the console handler.
LOGGING["handlers"]["console"]["filters"] = [  # type: ignore[index]
    "suppress_health_checks",
    "slow_queries",
]

LOGGING["loggers"]["django.db.backends"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["common"]["level"] = "DEBUG"  # type: ignore[index]
