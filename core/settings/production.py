"""Production settings — Railway deployment."""

import os
import sys

from .base import *

# --- Required environment variables ---
# Fail fast at boot rather than crash with a 500 on first request.
_REQUIRED_ENV: tuple[str, ...] = (
    "DJANGO_SECRET_KEY",
    "DATABASE_URL",
)
_missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
if _missing:
    sys.stderr.write(
        f"FATAL: missing required production env vars: {', '.join(_missing)}\n",
    )
    raise SystemExit(78)  # EX_CONFIG

# --- Allowed hosts ---
# Railway's internal health checker always sends Host: healthcheck.railway.app.
# Without it ALLOWED_HOSTS rejects the probe → DisallowedHost → deploy hangs.
# RAILWAY_PUBLIC_DOMAIN is injected automatically by Railway with the
# service's public URL (e.g. judah-production.up.railway.app).

_railway_hosts: list[str] = [
    "healthcheck.railway.app",  # Railway internal health probe (always present)
    ".railway.app",  # wildcard: covers *.up.railway.app and previews
]
_public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if _public_domain:
    _railway_hosts.append(_public_domain)

ALLOWED_HOSTS = list(ALLOWED_HOSTS) + _railway_hosts

# --- Security ---

DEBUG = False

# Deliberately no permissive production override: base.py defaults automatic
# assignment to False when AUTO_ASSIGNMENT_ENABLED is absent.

# Railway terminates TLS at its edge proxy and forwards requests over plain
# HTTP internally.  Without SECURE_PROXY_SSL_HEADER Django treats every
# request as insecure and SECURE_SSL_REDIRECT creates an infinite loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Railway enforces HTTPS at its edge; the container only receives plain HTTP
# internally. Setting SECURE_SSL_REDIRECT=True here causes Django to return
# 301 on every request (including the health-check probe from 100.64.x.x),
# because Railway's internal health checker sends no X-Forwarded-Proto header.
# SSL redirect is NOT needed — Railway already handles it at the proxy layer.
SECURE_SSL_REDIRECT = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# --- Database ---
# Supabase Supavisor transaction-mode pooler (port 6543) does not support
# persistent connections — CONN_MAX_AGE must be 0.
# Direct connection or session-mode pooler (port 5432) can safely reuse
# connections; we default to 60 s there.

if "default" in DATABASES:
    _db_port = str(DATABASES["default"].get("PORT") or "5432")
    DATABASES["default"]["CONN_MAX_AGE"] = 0 if _db_port == "6543" else 60
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("connect_timeout", 10)
    _runtime_environment = (
        os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("DJANGO_ENV") or "production"
    ).strip()
    _runtime_service = os.environ.get("RAILWAY_SERVICE_NAME", "unknown-service").strip()
    DATABASES["default"]["OPTIONS"].update(
        {"application_name": f"judah:{_runtime_environment}:{_runtime_service}"[:63]}
    )
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# --- Logging ---
# JSON format is already selected in base.py when DJANGO_ENV=production.
# Tighten root level to ERROR in production; app loggers keep DEBUG/INFO.

LOGGING["root"]["level"] = "ERROR"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]
