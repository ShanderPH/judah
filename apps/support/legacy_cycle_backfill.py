"""Deterministic, restartable legacy conversation-cycle backfill (Gate E)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import transaction

from apps.support.models import (
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ClosedConversation,
    ConversationReassignment,
    NewConversation,
    SupportConversationCycle,
)


@dataclass(slots=True)
class BackfillReport:
    """PII-free counters and quarantined row identifiers for one run."""

    scanned_tickets: int = 0
    created_cycles: int = 0
    reused_cycles: int = 0
    linked_rows: int = 0
    ambiguous_rows: int = 0
    quarantined: list[dict[str, str]] = field(default_factory=list)
    next_cursor: str = ""

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation."""
        return asdict(self)


def _legacy_key(model_name: str, row_id: object) -> str:
    evidence = f"{model_name}:{row_id}"
    return f"legacy:v1:{hashlib.sha256(evidence.encode()).hexdigest()}"


def _quarantine(report: BackfillReport, model_name: str, row_id: object, reason: str) -> None:
    report.ambiguous_rows += 1
    report.quarantined.append({"model": model_name, "row_id": str(row_id), "reason": reason})


def _create_or_get_cycle(
    *,
    ticket_id: str,
    model_name: str,
    row_id: object,
    entered_at: datetime | None,
    state: str,
    closed_at: datetime | None,
) -> tuple[SupportConversationCycle, bool]:
    portal_id = str(getattr(settings, "HUBSPOT_PORTAL_ID", "")).strip()
    if not portal_id:
        raise ValueError("HUBSPOT_PORTAL_ID is required for cycle backfill")
    evidence = f"{model_name}:{row_id}"
    defaults = {
        "source_system": "hubspot",
        "source_account_id": portal_id,
        "hubspot_ticket_id": ticket_id,
        "entered_stage_at": entered_at,
        "identity_source": "legacy_backfill",
        "identity_evidence_key": evidence,
        "state": state,
        "opened_at": entered_at or closed_at,
        "closed_at": closed_at,
    }
    return SupportConversationCycle.objects.get_or_create(cycle_key=_legacy_key(model_name, row_id), defaults=defaults)


def _link(row: object, cycle: SupportConversationCycle, report: BackfillReport) -> None:
    if row.cycle_id is None:  # type: ignore[attr-defined]
        type(row).objects.filter(pk=row.pk, cycle__isnull=True).update(cycle=cycle)
        report.linked_rows += 1


def _cycle_for_active_ticket(ticket_id: str) -> SupportConversationCycle | None:
    return SupportConversationCycle.objects.filter(
        hubspot_ticket_id=ticket_id,
        state__in=["queued", "assigned", "repair_required"],
    ).first()


@transaction.atomic
def backfill_legacy_cycles(*, limit: int = 500, after: str = "", ticket_id: str = "") -> BackfillReport:
    """Backfill one deterministic ticket batch without external API calls."""
    report = BackfillReport()
    ticket_ids = set(NewConversation.objects.filter(cycle__isnull=True).values_list("hubspot_ticket_id", flat=True))
    ticket_ids.update(
        AssignedConversation.objects.filter(cycle__isnull=True).values_list("hubspot_ticket_id", flat=True)
    )
    ticket_ids.update(ClosedConversation.objects.filter(cycle__isnull=True).values_list("hubspot_ticket_id", flat=True))
    ticket_ids.update(AssignmentAttempt.objects.filter(cycle__isnull=True).values_list("ticket_id", flat=True))
    ordered = sorted(
        value for value in ticket_ids if (not after or value > after) and (not ticket_id or value == ticket_id)
    )[:limit]

    for current_ticket in ordered:
        report.scanned_tickets += 1
        active_rows = list(NewConversation.objects.filter(hubspot_ticket_id=current_ticket, cycle__isnull=True))
        active_rows += list(AssignedConversation.objects.filter(hubspot_ticket_id=current_ticket, cycle__isnull=True))
        if len(active_rows) > 1:
            for row in active_rows:
                _quarantine(report, type(row).__name__, row.pk, "multiple_active_projections")
        elif active_rows:
            row = active_rows[0]
            entered_at = row.entered_queue_at
            if entered_at is None:
                _quarantine(report, type(row).__name__, row.pk, "missing_queue_entry_timestamp")
            else:
                state = "queued" if isinstance(row, NewConversation) else "assigned"
                cycle, created = _create_or_get_cycle(
                    ticket_id=current_ticket,
                    model_name=type(row).__name__,
                    row_id=row.pk,
                    entered_at=entered_at,
                    state=state,
                    closed_at=None,
                )
                report.created_cycles += int(created)
                report.reused_cycles += int(not created)
                _link(row, cycle, report)

        for closed in ClosedConversation.objects.filter(hubspot_ticket_id=current_ticket, cycle__isnull=True).order_by(
            "closed_at", "pk"
        ):
            cycle, created = _create_or_get_cycle(
                ticket_id=current_ticket,
                model_name="ClosedConversation",
                row_id=closed.pk,
                entered_at=closed.entered_queue_at,
                state="closed",
                closed_at=closed.closed_at,
            )
            report.created_cycles += int(created)
            report.reused_cycles += int(not created)
            _link(closed, cycle, report)

        active_cycle = _cycle_for_active_ticket(current_ticket)
        attempts = AssignmentAttempt.objects.filter(ticket_id=current_ticket, cycle__isnull=True).select_related(
            "queue_row"
        )
        for attempt in attempts:
            cycle = attempt.queue_row.cycle if attempt.queue_row_id and attempt.queue_row.cycle_id else active_cycle
            if cycle is None:
                matching = SupportConversationCycle.objects.filter(
                    hubspot_ticket_id=current_ticket, state="closed", opened_at__lte=attempt.reserved_at
                ).order_by("-opened_at")
                cycle = matching.first()
            if cycle is None:
                _quarantine(report, "AssignmentAttempt", attempt.pk, "no_unambiguous_cycle")
                continue
            _link(attempt, cycle, report)
            AssignmentLog.objects.filter(assignment_attempt=attempt, cycle__isnull=True).update(cycle=cycle)

        cycles = SupportConversationCycle.objects.filter(hubspot_ticket_id=current_ticket).order_by("opened_at")
        for reassignment in ConversationReassignment.objects.filter(
            hubspot_ticket_id=current_ticket, cycle__isnull=True
        ):
            candidates = [
                c
                for c in cycles
                if c.opened_at
                and c.opened_at <= reassignment.reassigned_at
                and (not c.closed_at or reassignment.reassigned_at <= c.closed_at)
            ]
            if len(candidates) == 1:
                _link(reassignment, candidates[0], report)
            else:
                _quarantine(report, "ConversationReassignment", reassignment.pk, "ambiguous_cycle_window")

        for log in AssignmentLog.objects.filter(
            ticket_id=current_ticket, cycle__isnull=True, assignment_attempt__isnull=True
        ):
            _quarantine(report, "AssignmentLog", log.pk, "log_without_attempt")
        report.next_cursor = current_ticket
    return report
