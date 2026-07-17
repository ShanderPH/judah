"""Staging settings — production-safe deployment with richer diagnostics."""

from decouple import config

from .production import *

# Staging is externally reachable, so every security and deployment setting
# comes from production.py (DEBUG=False, secure cookies, proxy handling,
# Railway hosts and database health checks). Only log verbosity differs.
LOGGING["root"]["level"] = "INFO"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "INFO"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["common"]["level"] = "DEBUG"  # type: ignore[index]

# A staging environment must never change assignment eligibility in a shared
# support database by default. Enable only after DB, Redis and HubSpot are all
# confirmed to be isolated from production.
AGENT_STATUS_SYNC_ENABLED = config("AGENT_STATUS_SYNC_ENABLED", default=False, cast=bool)
