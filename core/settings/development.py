"""Development settings."""

from .base import *  # noqa: F401, F403

DEBUG = True

INSTALLED_APPS = INSTALLED_APPS + [  # noqa: F405
    "debug_toolbar",
    "django_extensions",
]

MIDDLEWARE = [  # noqa: F405
    "debug_toolbar.middleware.DebugToolbarMiddleware",
] + MIDDLEWARE  # noqa: F405

INTERNAL_IPS = ["127.0.0.1", "localhost"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
