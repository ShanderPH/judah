"""Test settings — optimised for speed."""

from decouple import config

from .base import *

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("TEST_DB_NAME", default="judah_test"),
        "USER": config("TEST_DB_USER", default="judah"),
        "PASSWORD": config("TEST_DB_PASSWORD", default="judah_dev_password"),
        "HOST": config("TEST_DB_HOST", default="localhost"),
        "PORT": config("TEST_DB_PORT", default="5432"),
    }
}

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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {},
    "loggers": {},
}
