"""Test settings — optimised for speed."""

import json

from .base import *

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = False

# Synthetic provider contract: tests never load deployed configuration or manifests.
HUBSPOT_PROVIDER_CONFIG_JSON = json.dumps(
    {
        "contract_version": "1",
        "app": {"uid": "test_app", "config": {"auth": {"requiredScopes": ["tickets", "settings.users.read"]}}},
        "webhooks": {
            "uid": "test_webhooks",
            "config": {
                "settings": {"targetUrl": "https://example.test/webhooks/hubspot", "maxConcurrentRequests": 10},
                "subscriptions": {
                    "hubEvents": [],
                    "legacyCrmObjects": [
                        {"subscriptionType": "ticket.propertyChange", "propertyName": name, "active": True}
                        for name in ("hs_v2_date_entered_101", "hs_v2_date_entered_102", "hubspot_owner_id")
                    ],
                },
            },
        },
    }
)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
N8N_BOT_DELIVERY_ENABLED = True

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
