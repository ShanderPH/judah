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

# Tests opt into the legacy-compatible assignment lane explicitly. Individual
# Gate B tests override these controls to prove fail-closed behavior.
AUTO_ASSIGNMENT_ENABLED = True
ABSENCE_SAFE_ELIGIBILITY_SHADOW = False

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["application_name"] = "judah:local-test:pytest"  # type: ignore[index]

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
