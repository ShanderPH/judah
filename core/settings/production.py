"""Production settings — Railway deployment."""

from .base import *

# --- Security ---

DEBUG = False

# Railway terminates TLS at its edge proxy and forwards requests over plain
# HTTP internally.  Without SECURE_PROXY_SSL_HEADER Django treats every
# request as insecure and SECURE_SSL_REDIRECT creates an infinite loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

SECURE_SSL_REDIRECT = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# --- Database ---
# Increase connection reuse for production traffic.
# Supabase direct (port 5432) supports persistent connections.
# If using PgBouncer (port 6543) set this to 0.

if "default" in DATABASES:
    DATABASES["default"].setdefault("CONN_MAX_AGE", 60)
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("connect_timeout", 10)

# --- Logging ---
# JSON format is already selected in base.py when DJANGO_ENV=production.
# Tighten root level to ERROR in production; app loggers keep DEBUG/INFO.

LOGGING["root"]["level"] = "ERROR"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]
