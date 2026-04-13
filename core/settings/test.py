"""Test settings — optimised for speed."""

from .base import *

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = False

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CORS_ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {},
    "loggers": {},
}
