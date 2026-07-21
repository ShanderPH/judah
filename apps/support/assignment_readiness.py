"""Machine-readable readiness evaluation for the assignment writer."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count, Q
from django.utils import timezone

from apps.support.availability_runtime import (
    availability_writer_id,
    is_authoritative_availability_runtime,
    may_assign,
)
from apps.support.models import Agent, AssignmentAttempt

# (label, model name, ticket column) of every projection that can reference a
# conversation cycle after migration 0020.
_CYCLE_PROJECTION_TABLES = (
    ("new_conversations", "NewConversation", "hubspot_ticket_id"),
    ("assigned_conversations", "AssignedConversation", "hubspot_ticket_id"),
    ("closed_conversations", "ClosedConversation", "hubspot_ticket_id"),
    ("assignment_attempts", "AssignmentAttempt", "ticket_id"),
    ("assignment_logs", "AssignmentLog", "ticket_id"),
    ("conversation_reassignments", "ConversationReassignment", "hubspot_ticket_id"),
)


def _conversation_cycle_checks() -> dict[str, Any]:
    """Return PII-free conversation-cycle posture and projection coverage.

    Only booleans and aggregate counts are exposed: the portal ID itself,
    ticket IDs, names, emails, owners, and payloads are never included.
    """
    from django.apps import apps as django_apps
    from django.db.models import F

    checks: dict[str, Any] = {
        "portal_configured": bool(str(getattr(settings, "HUBSPOT_PORTAL_ID", "")).strip()),
        "enforced": bool(getattr(settings, "CONVERSATION_CYCLES_ENFORCED", False)),
    }
    applied = (
        MigrationRecorder(connection)
        .migration_qs.filter(
            app="support",
            name="0020_conversation_cycles_expand",
        )
        .exists()
    )
    checks["migration_applied"] = applied
    if not applied:
        return checks

    coverage: dict[str, dict[str, int]] = {}
    for label, model_name, ticket_field in _CYCLE_PROJECTION_TABLES:
        model = django_apps.get_model("support", model_name)
        total = model.objects.count()
        with_cycle = model.objects.filter(cycle__isnull=False).count()
        ticket_mismatch = (
            model.objects.filter(cycle__isnull=False).exclude(**{ticket_field: F("cycle__hubspot_ticket_id")}).count()
        )
        coverage[label] = {
            "total": total,
            "with_cycle": with_cycle,
            "null_cycle": total - with_cycle,
            "ticket_mismatch": ticket_mismatch,
        }
    checks["projection_coverage"] = coverage
    checks["projection_mismatches"] = sum(item["ticket_mismatch"] for item in coverage.values())
    checks["legacy_rows"] = sum(item["null_cycle"] for item in coverage.values())

    cycle_model = django_apps.get_model("support", "SupportConversationCycle")
    cycle_counts = {
        row["state"]: row["count"] for row in cycle_model.objects.values("state").annotate(count=Count("id"))
    }
    checks["total_cycles"] = sum(cycle_counts.values())
    checks["cycles_by_state"] = cycle_counts
    checks["queued_without_dispatch"] = cycle_model.objects.filter(
        state="queued",
        new_conversations__isnull=True,
    ).count()
    checks["legacy_writers_detected"] = checks["legacy_rows"] > 0
    checks["enforcement_ready"] = all(
        (
            checks["portal_configured"],
            checks["migration_applied"],
            checks["legacy_rows"] == 0,
            checks["projection_mismatches"] == 0,
            checks["queued_without_dispatch"] == 0,
        )
    )
    return checks


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

    checks["conversation_cycles"] = _conversation_cycle_checks()
    cycle_checks = checks["conversation_cycles"]
    if cycle_checks.get("projection_mismatches"):
        reasons.append("conversation_cycle_projection_mismatch")
    if cycle_checks.get("legacy_writers_detected"):
        reasons.append("conversation_cycle_legacy_rows")
    if cycle_checks.get("queued_without_dispatch"):
        reasons.append("conversation_cycle_dispatch_missing")
    if cycle_checks.get("enforced") and not cycle_checks.get("enforcement_ready"):
        reasons.append("conversation_cycle_enforcement_unsafe")

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
