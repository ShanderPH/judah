"""Machine-readable readiness evaluation for the assignment writer."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Q
from django.utils import timezone

from apps.support.availability_runtime import (
    availability_writer_id,
    is_authoritative_availability_runtime,
    may_assign,
)
from apps.support.models import Agent, AssignmentAttempt


def evaluate_assignment_readiness() -> dict[str, Any]:
    """Evaluate authority, rollout posture, schema, SAT freshness, and repairs."""
    reasons: list[str] = []
    checks: dict[str, Any] = {}

    checks["authoritative_runtime"] = is_authoritative_availability_runtime()
    if not checks["authoritative_runtime"]:
        reasons.append("runtime_not_authoritative")
    checks["automatic_assignment_enabled"] = bool(settings.AUTO_ASSIGNMENT_ENABLED)
    if not checks["automatic_assignment_enabled"]:
        reasons.append("automatic_assignment_disabled")
    checks["absence_safe_enforced"] = bool(settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED)
    if not checks["absence_safe_enforced"]:
        reasons.append("absence_safe_enforcement_disabled")
    checks["assignment_posture_allowed"] = may_assign()
    if not checks["assignment_posture_allowed"]:
        reasons.append("assignment_posture_blocked")

    applied = (
        MigrationRecorder(connection)
        .migration_qs.filter(
            app="support",
            name="0017_durable_assignment_protocol",
        )
        .exists()
    )
    checks["durable_migration_applied"] = applied
    if not applied:
        reasons.append("durable_migration_missing")

    freshness_cutoff = timezone.now() - timedelta(seconds=int(settings.AVAILABILITY_FRESHNESS_SECONDS))
    active_agents = Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
    stale_agents = (
        active_agents.filter(availability_observed_at__lt=freshness_cutoff).count()
        + active_agents.filter(availability_observed_at__isnull=True).count()
    )
    checks["stale_sat_agents"] = stale_agents
    if stale_agents:
        reasons.append("sat_observations_stale")

    stuck_cutoff = timezone.now() - timedelta(seconds=int(getattr(settings, "ASSIGNMENT_STUCK_AFTER_SECONDS", 120)))
    stuck_attempts = (
        AssignmentAttempt.objects.filter(
            state__in=(
                AssignmentAttempt.State.RESERVED,
                AssignmentAttempt.State.REPAIR_REQUIRED,
            ),
            updated_at__lte=stuck_cutoff,
        ).count()
        if applied
        else 0
    )
    checks["stuck_attempts"] = stuck_attempts
    if stuck_attempts:
        reasons.append("assignment_attempts_stuck")

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, current_setting('application_name', true)")
        role, application_name = cursor.fetchone()
    checks["writer_role"] = role
    checks["application_name_configured"] = bool(application_name)
    checks["writer_id"] = availability_writer_id()
    if not application_name:
        reasons.append("database_application_name_missing")

    state = "healthy"
    if reasons:
        state = (
            "unhealthy"
            if any(
                reason
                in {
                    "runtime_not_authoritative",
                    "durable_migration_missing",
                    "assignment_attempts_stuck",
                }
                for reason in reasons
            )
            else "degraded"
        )
    return {
        "state": state,
        "ready": state == "healthy",
        "reasons": reasons,
        "checks": checks,
    }
