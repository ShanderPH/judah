"""Read-only aggregate profiling of legacy assignment data (Gate A, DB-01).

Produces the deterministic, PII-free counts needed to prepare the future
cycle backfill (Gate E). Every function performs SELECT-only ORM queries;
no row is created, updated, deleted, closed, reopened, or reconciled, and no
HubSpot API call is made.

Presentation lives in the ``profile_legacy_cycles`` management command; this
module only collects numbers so tests can assert them directly against local
fixtures.
"""

from __future__ import annotations

from django.db.models import Count, F

from apps.support.durable_assignment_service import LIVE_STATES
from apps.support.models import (
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ClosedConversation,
    ConversationReassignment,
    NewConversation,
)


def _ticket_ids(model: type[NewConversation] | type[AssignedConversation] | type[ClosedConversation]):
    """Return a subquery of ticket IDs present in one operational table."""
    return model.objects.values("hubspot_ticket_id")


def collect_legacy_cycle_profile() -> dict[str, int]:
    """Collect aggregate, PII-free counts describing cycle-hostile legacy data.

    Returns:
        An insertion-ordered mapping of metric name to count. Keys are stable
        so the rendered output is deterministic across runs over the same
        data. Counts are whole-table aggregates; no identifier, name, or
        email is exposed.
    """
    queue_ids = _ticket_ids(NewConversation)
    assigned_ids = _ticket_ids(AssignedConversation)
    closed_ids = _ticket_ids(ClosedConversation)

    attempts_per_ticket = AssignmentAttempt.objects.values("ticket_id").annotate(n=Count("id"))
    logs_per_ticket = AssignmentLog.objects.values("ticket_id").annotate(n=Count("id"))

    completed_attempts = AssignmentAttempt.objects.filter(state=AssignmentAttempt.State.COMPLETED)

    return {
        # Totals for reconciliation context.
        "total_queue_rows": NewConversation.objects.count(),
        "total_assigned_rows": AssignedConversation.objects.count(),
        "total_closed_rows": ClosedConversation.objects.count(),
        "total_attempts": AssignmentAttempt.objects.count(),
        "total_logs": AssignmentLog.objects.count(),
        "total_reassignments": ConversationReassignment.objects.count(),
        # Tickets simultaneously present in more than one lifecycle table.
        "tickets_in_queue_and_assigned": NewConversation.objects.filter(hubspot_ticket_id__in=assigned_ids).count(),
        "tickets_in_queue_and_closed": NewConversation.objects.filter(hubspot_ticket_id__in=closed_ids).count(),
        "tickets_in_assigned_and_closed": AssignedConversation.objects.filter(hubspot_ticket_id__in=closed_ids).count(),
        "tickets_in_all_three_tables": NewConversation.objects.filter(hubspot_ticket_id__in=assigned_ids)
        .filter(hubspot_ticket_id__in=closed_ids)
        .count(),
        # Incident signature: a completed attempt coexisting with active rows
        # for the same ticket (blocked conclusion of a later attendance).
        "tickets_with_completed_attempt_and_queue_row": (
            completed_attempts.filter(ticket_id__in=queue_ids).values("ticket_id").distinct().count()
        ),
        "tickets_with_completed_attempt_and_assigned_row": (
            completed_attempts.filter(ticket_id__in=assigned_ids).values("ticket_id").distinct().count()
        ),
        # Multiplicity per ticket: reassignments vs. full new attendances are
        # currently indistinguishable without a cycle key.
        "tickets_with_multiple_attempts": attempts_per_ticket.filter(n__gt=1).count(),
        "tickets_with_multiple_logs": logs_per_ticket.filter(n__gt=1).count(),
        "tickets_with_multiple_live_attempts": (
            AssignmentAttempt.objects.filter(state__in=LIVE_STATES)
            .values("ticket_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .count()
        ),
        # Attempt state distribution relevant to repair/backfill.
        "live_attempts": AssignmentAttempt.objects.filter(state__in=LIVE_STATES).count(),
        "external_applied_attempts": AssignmentAttempt.objects.filter(
            state=AssignmentAttempt.State.EXTERNAL_APPLIED
        ).count(),
        "repair_required_attempts": AssignmentAttempt.objects.filter(
            state=AssignmentAttempt.State.REPAIR_REQUIRED
        ).count(),
        "completed_attempts": completed_attempts.count(),
        # Timestamp correlation and provability gaps.
        "attempts_reserved_before_queue_entry": AssignmentAttempt.objects.filter(
            queue_row__isnull=False,
            reserved_at__lt=F("queue_row__entered_queue_at"),
        ).count(),
        "closed_before_assigned": ClosedConversation.objects.filter(
            assigned_at__isnull=False,
            closed_at__lt=F("assigned_at"),
        ).count(),
        "assigned_rows_without_entered_queue_at": AssignedConversation.objects.filter(
            entered_queue_at__isnull=True
        ).count(),
        "closed_rows_without_entered_queue_at": ClosedConversation.objects.filter(
            entered_queue_at__isnull=True
        ).count(),
        "closed_rows_without_assigned_at": ClosedConversation.objects.filter(assigned_at__isnull=True).count(),
        # Provenance gaps between attempts and logs.
        "completed_attempts_without_log": completed_attempts.filter(assignment_log__isnull=True).count(),
        "logs_without_attempt": AssignmentLog.objects.filter(assignment_attempt__isnull=True).count(),
    }
