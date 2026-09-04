"""Machine-readable readiness evaluation for the assignment writer."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from apps.support.availability_runtime import (
    availability_writer_id,
    is_authoritative_availability_runtime,
    may_assign,
)
from apps.support.models import (
    ASSIGNMENT_ATTEMPT_NON_TERMINAL_STATES,
    Agent,
    AssignmentAttempt,
    NewConversation,
    OpeningAssignmentCohort,
)

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

    cohort_migration_applied = (
        MigrationRecorder(connection).migration_qs.filter(app="support", name="0030_opening_assignment_cohort").exists()
    )
    checks["opening_cohort_mode"] = str(settings.OPENING_COHORT_BARRIER_MODE)
    checks["opening_cohort_migration_applied"] = cohort_migration_applied

    now = timezone.now()
    active_cohort = (
        OpeningAssignmentCohort.objects.filter(state=OpeningAssignmentCohort.State.ACTIVE)
        .order_by("deadline_at")
        .first()
        if cohort_migration_applied
        else None
    )
    checks["opening_cohort_active"] = active_cohort is not None
    checks["opening_cohort_age_seconds"] = (
        max(0, int((now - active_cohort.cohort_observed_at).total_seconds())) if active_cohort else 0
    )
    checks["opening_cohort_deadline_expired"] = bool(active_cohort and active_cohort.deadline_at <= now)
    checks["opening_cohort_deferred_backlog"] = (
        NewConversation.objects.filter(
            automatic_assignment_eligible=True,
            next_assignment_attempt_at=active_cohort.recheck_at,
            entered_queue_at__lt=active_cohort.window_started_at,
        ).count()
        if active_cohort
        else 0
    )
    if checks["opening_cohort_deadline_expired"] and checks["opening_cohort_deferred_backlog"]:
        reasons.append("opening_cohort_deadline_expired")
    freshness_cutoff = now - timedelta(seconds=int(settings.AVAILABILITY_FRESHNESS_SECONDS))
    active_agents = Agent.objects.filter(Q(is_active=True) | Q(is_active__isnull=True))
    stale_agents = (
        active_agents.filter(availability_observed_at__lt=freshness_cutoff).count()
        + active_agents.filter(availability_observed_at__isnull=True).count()
    )
    checks["stale_sat_agents"] = stale_agents
    last_sat_success = active_agents.aggregate(last=Max("sat_last_heartbeat_at"))["last"]
    checks["sat_last_success_at"] = last_sat_success.isoformat() if last_sat_success else None
    checks["sat_last_success_age_seconds"] = (
        max(0, int((now - last_sat_success).total_seconds())) if last_sat_success else None
    )
    if stale_agents:
        reasons.append("sat_observations_stale")

    stuck_cutoff = timezone.now() - timedelta(seconds=int(getattr(settings, "ASSIGNMENT_STUCK_AFTER_SECONDS", 120)))
    stuck_by_state = (
        {
            row["state"]: row["count"]
            for row in AssignmentAttempt.objects.filter(
                state__in=ASSIGNMENT_ATTEMPT_NON_TERMINAL_STATES,
                updated_at__lte=stuck_cutoff,
            )
            .values("state")
            .annotate(count=Count("id"))
        }
        if applied
        else {}
    )
    stuck_attempts = sum(stuck_by_state.values())
    checks["stuck_attempts"] = stuck_attempts
    checks["stuck_attempts_by_state"] = stuck_by_state
    if stuck_attempts:
        reasons.append("assignment_attempts_stuck")

    attempts_by_state = (
        {row["state"]: row["count"] for row in AssignmentAttempt.objects.values("state").annotate(count=Count("id"))}
        if applied
        else {}
    )
    checks["attempts_by_state"] = attempts_by_state
    oldest_non_terminal = (
        AssignmentAttempt.objects.filter(state__in=ASSIGNMENT_ATTEMPT_NON_TERMINAL_STATES)
        .order_by("updated_at")
        .values_list("updated_at", flat=True)
        .first()
        if applied
        else None
    )
    checks["oldest_non_terminal_age_seconds"] = (
        max(0, int((now - oldest_non_terminal).total_seconds())) if oldest_non_terminal else 0
    )
    ready_queue = NewConversation.objects.filter(
        automatic_assignment_eligible=True,
        queue_status__in=(NewConversation.QueueStatus.PENDING, NewConversation.QueueStatus.QUEUED),
    ).filter(Q(next_assignment_attempt_at__isnull=True) | Q(next_assignment_attempt_at__lte=now))
    checks["ready_queue_depth"] = ready_queue.count()
    oldest_ready = ready_queue.order_by("entered_queue_at").values_list("entered_queue_at", flat=True).first()
    checks["oldest_ready_age_seconds"] = (
        max(0, int((now - oldest_ready).total_seconds())) if oldest_ready is not None else 0
    )
    poisoned = NewConversation.objects.filter(queue_status=NewConversation.QueueStatus.FAILED)
    checks["poisoned_queue_rows"] = {
        row["failure_code"] or "unclassified": row["count"]
        for row in poisoned.values("failure_code").annotate(count=Count("id"))
    }
    checks["expired_claims"] = (
        NewConversation.objects.filter(
            claim_expires_at__lte=now,
        )
        .exclude(claim_owner_token="")
        .count()
    )
    checks["completed_attempt_queue_conflicts"] = AssignmentAttempt.objects.filter(
        state=AssignmentAttempt.State.COMPLETED,
        queue_row__isnull=False,
    ).count()
    checks["capacity_drift_agents"] = active_agents.filter(
        current_simultaneous_chats__gt=F("max_simultaneous_chats")
    ).count()
    if checks["poisoned_queue_rows"]:
        reasons.append("assignment_queue_poisoned_rows")

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, current_setting('application_name', true)")
        role, application_name = cursor.fetchone()
    checks["writer_role"] = role
    checks["application_name_configured"] = bool(application_name)
    checks["writer_id"] = availability_writer_id()
    checks["release_sha"] = str(getattr(settings, "GIT_SHA", ""))
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

    try:
        from apps.webhooks.models import DeadLetterQueue, OutboxEvent, WebhookEvent

        oldest_unprocessed = (
            WebhookEvent.objects.filter(processed=False)
            .order_by("received_at")
            .values_list("received_at", flat=True)
            .first()
        )
        checks["webhook_lag_seconds"] = (
            max(0, int((now - oldest_unprocessed).total_seconds())) if oldest_unprocessed else 0
        )
        checks["webhook_duplicate_events"] = WebhookEvent.objects.filter(
            processing_status=WebhookEvent.ProcessingStatus.IGNORED,
            ignored_reason__icontains="duplicate",
        ).count()
        checks["webhook_dlq_depth"] = DeadLetterQueue.objects.count()
        checks["outbox_by_status"] = {
            row["status"]: row["count"] for row in OutboxEvent.objects.values("status").annotate(count=Count("id"))
        }
        checks["integration_metrics_available"] = True
    except Exception:
        checks["integration_metrics_available"] = False

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


def emit_assignment_readiness_metrics(readiness: dict[str, Any]) -> None:
    """Emit bounded-cardinality metrics from one PII-free readiness snapshot."""
    from apps.webhooks.metrics import emit_metric

    checks = readiness["checks"]
    state = str(readiness["state"])
    emit_metric("assignment_ready", int(bool(readiness["ready"])), kind="gauge", state=state)
    emit_metric("assignment_sat_stale_agents", checks["stale_sat_agents"], kind="gauge")
    if checks["sat_last_success_age_seconds"] is not None:
        emit_metric(
            "assignment_sat_last_success_age_seconds",
            checks["sat_last_success_age_seconds"],
            kind="gauge",
        )
    emit_metric("assignment_queue_ready_depth", checks["ready_queue_depth"], kind="gauge")
    emit_metric("assignment_queue_oldest_age_seconds", checks["oldest_ready_age_seconds"], kind="gauge")
    emit_metric("assignment_capacity_drift_agents", checks["capacity_drift_agents"], kind="gauge")
    emit_metric(
        "assignment_cohort_active",
        int(bool(checks.get("opening_cohort_active", False))),
        kind="gauge",
        mode=str(checks.get("opening_cohort_mode", "off")),
    )
    for attempt_state, count in checks["attempts_by_state"].items():
        emit_metric("assignment_attempts", count, kind="gauge", state=attempt_state)
    for attempt_state, count in checks["stuck_attempts_by_state"].items():
        emit_metric("assignment_stuck_attempts", count, kind="gauge", state=attempt_state)
    if checks["integration_metrics_available"]:
        emit_metric("assignment_webhook_lag_seconds", checks["webhook_lag_seconds"], kind="gauge")
        emit_metric("assignment_webhook_duplicates", checks["webhook_duplicate_events"], kind="gauge")
        emit_metric("assignment_webhook_dlq_depth", checks["webhook_dlq_depth"], kind="gauge")
        for outbox_status, count in checks["outbox_by_status"].items():
            emit_metric("assignment_outbox_events", count, kind="gauge", state=outbox_status)
