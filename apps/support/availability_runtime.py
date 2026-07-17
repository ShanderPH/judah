"""Runtime authority guard for availability and automatic assignment writers."""

from __future__ import annotations

import os

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def runtime_environment() -> str:
    """Return the effective deployment environment without exposing secrets."""
    railway_environment = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "").strip().lower()
    django_environment = os.environ.get("DJANGO_ENV", "development").strip().lower()
    return railway_environment or django_environment


def availability_writer_id() -> str:
    """Build an auditable identity for the current runtime."""
    parts = (
        os.environ.get("RAILWAY_PROJECT_NAME", ""),
        os.environ.get("RAILWAY_ENVIRONMENT_NAME", ""),
        os.environ.get("RAILWAY_SERVICE_NAME", ""),
        os.environ.get("RAILWAY_DEPLOYMENT_ID", ""),
        os.environ.get("RAILWAY_REPLICA_ID", ""),
    )
    identity = "/".join(part.strip() for part in parts if part.strip())
    return identity or f"local/{runtime_environment()}"


def is_authoritative_availability_runtime() -> bool:
    """Return whether this runtime may mutate authoritative availability."""
    django_environment = os.environ.get("DJANGO_ENV", "development").strip().lower()
    if django_environment == "test":
        return True

    authority = str(settings.AVAILABILITY_AUTHORITY_ENVIRONMENT).strip().lower()
    railway_environment = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "").strip().lower()
    return django_environment == authority and (not railway_environment or railway_environment == authority)


def is_auto_assignment_runtime_allowed() -> bool:
    """Return whether automatic assignment may execute in this runtime."""
    return bool(settings.AUTO_ASSIGNMENT_ENABLED) and is_authoritative_availability_runtime()


def log_runtime_rejection(operation: str) -> None:
    """Emit a structured event when an environment fence rejects a writer."""
    logger.warning(
        "runtime_authority_rejected",
        operation=operation,
        runtime_environment=runtime_environment(),
        authority_environment=settings.AVAILABILITY_AUTHORITY_ENVIRONMENT,
        writer_id=availability_writer_id(),
    )
