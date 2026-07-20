"""Runtime capability guards for routing-state writers."""

from __future__ import annotations

import os
from enum import StrEnum
from uuid import UUID

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


class RoutingCapability(StrEnum):
    """Capabilities that may mutate authoritative routing state."""

    INGEST_QUEUE = "ingest_queue"
    RECONCILE_QUEUE = "reconcile_queue"
    ASSIGN = "assign"
    WRITE_ROUTING_STATE = "write_routing_state"


# Keep this inventory explicit so code review and regression tests can detect
# newly introduced routing writers that have not selected an authority gate.
ROUTING_WRITER_CAPABILITIES: dict[str, RoutingCapability] = {
    "enqueue_new_ticket": RoutingCapability.INGEST_QUEUE,
    "process_new_ticket_event": RoutingCapability.INGEST_QUEUE,
    "sync_novo_stage_tickets": RoutingCapability.RECONCILE_QUEUE,
    "task_matchmaker_assign_single": RoutingCapability.INGEST_QUEUE,
    "task_matchmaker_drain_queue": RoutingCapability.ASSIGN,
    "matchmaker_assign_next": RoutingCapability.ASSIGN,
    "matchmaker_drain_queue": RoutingCapability.ASSIGN,
    "assign_pending_tickets": RoutingCapability.ASSIGN,
    "attempt_auto_assign": RoutingCapability.ASSIGN,
    "sat_heartbeat": RoutingCapability.WRITE_ROUTING_STATE,
    "sat_reset_daily_counters": RoutingCapability.WRITE_ROUTING_STATE,
    "sat_reconcile_agent_load": RoutingCapability.WRITE_ROUTING_STATE,
    "sync_all_agents_status_and_counts_optimized": RoutingCapability.WRITE_ROUTING_STATE,
    "sync_hubspot_team_to_agents": RoutingCapability.WRITE_ROUTING_STATE,
    "task_handle_ticket_closed": RoutingCapability.WRITE_ROUTING_STATE,
    "task_handle_owner_change": RoutingCapability.WRITE_ROUTING_STATE,
    "task_reconcile_agent_counts": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_create_agent": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_update_agent": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_inactivate_agent": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_reactivate_agent": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_manual_assign": RoutingCapability.WRITE_ROUTING_STATE,
    "admin_force_reassign": RoutingCapability.WRITE_ROUTING_STATE,
}


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
    railway_environment = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "").strip().lower()
    if django_environment == "test":
        return not railway_environment

    authority = str(settings.AVAILABILITY_AUTHORITY_ENVIRONMENT).strip().lower()
    return django_environment == authority and (not railway_environment or railway_environment == authority)


def may_ingest_queue() -> bool:
    """Return whether this runtime may persist authoritative queue intake."""
    return is_authoritative_availability_runtime()


def may_reconcile_queue() -> bool:
    """Return whether this runtime may rebuild authoritative queue state."""
    return is_authoritative_availability_runtime()


def _configured_canary_values() -> frozenset[str]:
    """Return non-empty raw canary values from settings."""
    configured = getattr(settings, "AUTO_ASSIGNMENT_CANARY_AGENT_IDS", ())
    values = configured.split(",") if isinstance(configured, str) else configured
    return frozenset(str(value).strip() for value in values if str(value).strip())


def automatic_assignment_canary_agent_ids() -> frozenset[str]:
    """Return validated local Agent UUIDs allowed during a canary."""
    valid_ids: set[str] = set()
    for value in _configured_canary_values():
        try:
            valid_ids.add(str(UUID(value)))
        except ValueError:
            logger.error("auto_assignment_canary_invalid_agent_id")
    return frozenset(valid_ids)


def is_automatic_assignment_canary_configured() -> bool:
    """Return whether a canary restriction was explicitly configured."""
    return bool(_configured_canary_values())


def may_assign() -> bool:
    """Return whether automatic owner mutation is enabled and safe."""
    if not is_authoritative_availability_runtime():
        return False
    if not bool(settings.AUTO_ASSIGNMENT_ENABLED):
        return False

    configured_canary = _configured_canary_values()
    canary_ids = automatic_assignment_canary_agent_ids()
    if configured_canary and len(canary_ids) != len(configured_canary):
        return False
    shadow_without_enforcement = bool(settings.ABSENCE_SAFE_ELIGIBILITY_SHADOW) and not bool(
        settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED
    )
    canary_without_enforcement = bool(configured_canary) and not bool(settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED)
    return not shadow_without_enforcement and not canary_without_enforcement


def may_write_routing_state() -> bool:
    """Return whether general routing reconciliation/manual writes are allowed."""
    return is_authoritative_availability_runtime()


def is_auto_assignment_runtime_allowed() -> bool:
    """Compatibility alias for the canonical assignment capability."""
    return may_assign()


def require_routing_writer_authority(operation: str) -> None:
    """Reject a routing writer before it performs database or network I/O."""
    if may_write_routing_state():
        return
    log_runtime_rejection(operation)
    from common.exceptions import ForbiddenError

    raise ForbiddenError("This runtime is not authorized to mutate support routing state.")


def log_runtime_rejection(operation: str) -> None:
    """Emit a structured event when an environment fence rejects a writer."""
    logger.warning(
        "runtime_authority_rejected",
        operation=operation,
        runtime_environment=runtime_environment(),
        authority_environment=settings.AVAILABILITY_AUTHORITY_ENVIRONMENT,
        writer_id=availability_writer_id(),
    )
