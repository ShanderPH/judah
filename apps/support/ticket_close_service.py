"""Materialize proven close occurrences without rewinding later attendances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import structlog
from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet

from apps.support.capacity_service import capacity_enforced, capacity_mode, ticket_transaction
from apps.support.conversation_cycle_service import InvalidStageTimestampError, parse_stage_entry_timestamp
from apps.support.models import (
    Agent,
    AssignedConversation,
    ClosedConversation,
    NewConversation,
    SupportConversationCycle,
    SupportTicketOccupancy,
)

logger = structlog.get_logger(__name__)


class CloseClassification(StrEnum):
    """Observable outcomes of occurrence reconciliation."""

    APPLIED_CURRENT = "applied_current"
    APPLIED_HISTORICAL = "applied_historical"
    DUPLICATE = "duplicate"
    NO_CYCLE = "no_cycle"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    REOPEN_NOT_MATERIALIZED = "reopen_not_materialized"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class TicketCloseOccurrence:
    """Provider occurrence time, independent of delivery and processing time."""

    ticket_id: str
    effective_at: datetime
    closing_owner_id: int | None = None
    source_event_id: str = ""


@dataclass(frozen=True)
class TicketCloseResult:
    """Explicit domain outcome; dry-run application outcomes describe eligibility."""

    classification: CloseClassification
    cycle_id: UUID | None = None
    closes_current_lifecycle: bool = False


def resolve_close_target(
    cycles: list[SupportConversationCycle], occurrence: TicketCloseOccurrence
) -> TicketCloseResult:
    """Resolve an interval only when every local cycle has comparable identity."""
    if not cycles:
        return TicketCloseResult(CloseClassification.NO_CYCLE)
    if (
        occurrence.effective_at.tzinfo is None
        or any(row.entered_stage_at is None for row in cycles)
        or len({(row.source_system, row.source_account_id) for row in cycles}) != 1
    ):
        return TicketCloseResult(CloseClassification.IDENTITY_UNAVAILABLE)
    ordered = sorted(cycles, key=lambda row: row.entered_stage_at)
    eligible = [row for row in ordered if row.entered_stage_at <= occurrence.effective_at]
    if not eligible:
        return TicketCloseResult(CloseClassification.NO_CYCLE)
    target = eligible[-1]
    historical = target.pk != ordered[-1].pk
    if target.state == SupportConversationCycle.State.CANCELLED:
        return TicketCloseResult(CloseClassification.CONFLICT, target.pk)
    if target.state == SupportConversationCycle.State.CLOSED:
        return TicketCloseResult(CloseClassification.DUPLICATE, target.pk)
    return TicketCloseResult(
        CloseClassification.APPLIED_HISTORICAL if historical else CloseClassification.APPLIED_CURRENT,
        target.pk,
        not historical,
    )


def _cycles(ticket_id: str) -> QuerySet[SupportConversationCycle]:
    """Return locally known service cycles for one ticket."""
    return SupportConversationCycle.objects.filter(hubspot_ticket_id=ticket_id).order_by("pk")


def recent_close_projection_inconsistencies(since: datetime) -> QuerySet[SupportConversationCycle]:
    """Find recent active cycles whose occupancy is closed without a close projection."""
    closed_occupancy = SupportTicketOccupancy.objects.filter(
        source_account_id=OuterRef("source_account_id"),
        hubspot_ticket_id=OuterRef("hubspot_ticket_id"),
        state="closed",
    )
    closed_projection = ClosedConversation.objects.filter(cycle_id=OuterRef("pk"))
    return (
        SupportConversationCycle.objects.filter(
            created_at__gte=since,
            state__in=[SupportConversationCycle.State.QUEUED, SupportConversationCycle.State.ASSIGNED],
        )
        .filter(Exists(closed_occupancy))
        .filter(~Exists(closed_projection))
    )


def _provider_decision(occurrence: TicketCloseOccurrence, snapshot: dict[str, object]) -> CloseClassification | None:
    """Reject a close when provider state proves a later active attendance."""
    from apps.integrations.hubspot.client import STAGE_FECHADO_ID, SUPPORT_PIPELINE_ID

    if str(snapshot.get("id")) != occurrence.ticket_id or not snapshot.get("stage") or not snapshot.get("pipeline"):
        return CloseClassification.CONFLICT
    entered_novo = snapshot.get("entered_novo_at")
    if entered_novo:
        try:
            reopened_at = parse_stage_entry_timestamp(str(entered_novo))
        except InvalidStageTimestampError:
            return CloseClassification.IDENTITY_UNAVAILABLE
        if reopened_at > occurrence.effective_at:
            return CloseClassification.REOPEN_NOT_MATERIALIZED
    if (
        snapshot["stage"] != STAGE_FECHADO_ID
        and snapshot["pipeline"] == SUPPORT_PIPELINE_ID
        and snapshot.get("archived") is not True
    ):
        return CloseClassification.REOPEN_NOT_MATERIALIZED
    return None


def reconcile_close_occurrence(
    occurrence: TicketCloseOccurrence, *, dry_run: bool = False, allow_legacy: bool = False
) -> TicketCloseResult:
    """Read provider before locks, then apply to the revalidated local interval."""
    from apps.integrations.hubspot.client import get_hubspot_client
    from apps.support.owner_reconciliation_service import CapacityObservationConflictError, reconcile_ticket

    initial = resolve_close_target(list(_cycles(occurrence.ticket_id)), occurrence)
    snapshot: dict[str, object] | None = None
    legacy = allow_legacy and initial.classification == CloseClassification.NO_CYCLE
    needs_occupancy = (initial.closes_current_lifecycle or legacy) and not dry_run and capacity_mode() != "off"
    captured_revision = None
    if needs_occupancy:
        with ticket_transaction(occurrence.ticket_id) as captured:
            captured_revision = captured.revision
    if initial.closes_current_lifecycle or (legacy and capacity_mode() != "off"):
        snapshot = get_hubspot_client().get_ticket_details(occurrence.ticket_id)
    if snapshot is not None and needs_occupancy:
        with ticket_transaction(occurrence.ticket_id) as locked:
            if locked.revision != captured_revision:
                raise CapacityObservationConflictError("Ticket revision changed after provider read")
            reconcile_ticket(
                occurrence.ticket_id,
                source="close",
                provider_data=snapshot,
                close_occurrence=occurrence,
            )
            result = apply_close_occurrence(occurrence, snapshot=snapshot, dry_run=dry_run, allow_legacy=allow_legacy)
            if result.classification in {
                CloseClassification.APPLIED_CURRENT,
                CloseClassification.APPLIED_HISTORICAL,
                CloseClassification.DUPLICATE,
            }:
                return result
            transaction.set_rollback(True)
        logger.warning(
            "ticket_close_occurrence",
            ticket_id=occurrence.ticket_id,
            cycle_id=str(result.cycle_id) if result.cycle_id else None,
            source_event_id=occurrence.source_event_id,
            classification=result.classification.value,
            effective_at=occurrence.effective_at.isoformat(),
            domain_applied=False,
            retryable=False,
        )
        return result
    return apply_close_occurrence(occurrence, snapshot=snapshot, dry_run=dry_run, allow_legacy=allow_legacy)


def classify_close_occurrence(
    cycles: list[SupportConversationCycle], occurrence: TicketCloseOccurrence, snapshot: dict[str, object] | None
) -> TicketCloseResult:
    """Validate temporal identity and provider state before any projection writes."""
    result = resolve_close_target(cycles, occurrence)
    if result.closes_current_lifecycle:
        rejection = (
            _provider_decision(occurrence, snapshot)
            if snapshot is not None
            else CloseClassification.PROVIDER_UNAVAILABLE
        )
        if rejection is not None:
            return TicketCloseResult(rejection, result.cycle_id)
    return result


def apply_close_occurrence(
    occurrence: TicketCloseOccurrence,
    *,
    snapshot: dict[str, object] | None = None,
    dry_run: bool = False,
    allow_legacy: bool = False,
) -> TicketCloseResult:
    """Apply only local writes; callers may supply an already revalidated snapshot."""
    with transaction.atomic():
        cycles = list(_cycles(occurrence.ticket_id).select_for_update())
        result = classify_close_occurrence(cycles, occurrence, snapshot)
        legacy = not cycles and allow_legacy and not settings.CONVERSATION_CYCLES_ENFORCED
        if legacy:
            result = TicketCloseResult(CloseClassification.APPLIED_CURRENT, closes_current_lifecycle=True)
        if legacy and snapshot is not None:
            rejection = _provider_decision(occurrence, snapshot)
            if rejection is not None:
                result = TicketCloseResult(rejection, result.cycle_id)
        if result.classification in {CloseClassification.APPLIED_CURRENT, CloseClassification.APPLIED_HISTORICAL}:
            target = next((row for row in cycles if row.pk == result.cycle_id), None)
            list(
                AssignedConversation.objects.select_for_update()
                .filter(cycle=target, hubspot_ticket_id=occurrence.ticket_id)
                .order_by("pk")
            )
            list(
                NewConversation.objects.select_for_update()
                .filter(cycle=target, hubspot_ticket_id=occurrence.ticket_id)
                .order_by("pk")
            )
            existing = (
                ClosedConversation.objects.filter(cycle=target)
                if target is not None
                else ClosedConversation.objects.filter(hubspot_ticket_id=occurrence.ticket_id, cycle__isnull=True)
            )
            active_legacy = target is None and (
                AssignedConversation.objects.filter(cycle__isnull=True, hubspot_ticket_id=occurrence.ticket_id).exists()
                or NewConversation.objects.filter(cycle__isnull=True, hubspot_ticket_id=occurrence.ticket_id).exists()
            )
            if existing.exists() and not active_legacy:
                classification = CloseClassification.CONFLICT if target is not None else CloseClassification.DUPLICATE
                result = TicketCloseResult(classification, result.cycle_id)
            elif not dry_run:
                _materialize(target, occurrence, current=result.closes_current_lifecycle)
        domain_applied = (
            result.classification
            in {
                CloseClassification.APPLIED_CURRENT,
                CloseClassification.APPLIED_HISTORICAL,
            }
            and not dry_run
        )
        transaction.on_commit(
            lambda: logger.info(
                "ticket_close_occurrence",
                ticket_id=occurrence.ticket_id,
                cycle_id=str(result.cycle_id) if result.cycle_id else None,
                source_event_id=occurrence.source_event_id,
                classification=result.classification.value,
                effective_at=occurrence.effective_at.isoformat(),
                domain_applied=domain_applied,
                retryable=result.classification == CloseClassification.PROVIDER_UNAVAILABLE,
            )
        )
        return result


def _minutes(start: datetime | None, end: datetime) -> Decimal | None:
    """Calculate elapsed minutes only when a start timestamp exists."""
    return Decimal(str(round((end - start).total_seconds() / 60, 2))) if start else None


def _materialize(target: SupportConversationCycle | None, occurrence: TicketCloseOccurrence, *, current: bool) -> None:
    """Move active projections into a closed record for the proven occurrence."""
    from apps.support.auto_assign_service import _transition_lifecycle_best_effort
    from apps.support.queue_service import decrement_agent_chat_count

    assigned = (
        AssignedConversation.objects.select_for_update()
        .filter(cycle=target, hubspot_ticket_id=occurrence.ticket_id)
        .first()
    )
    pending = NewConversation.objects.select_for_update().filter(cycle=target, hubspot_ticket_id=occurrence.ticket_id)
    list(pending)
    closing_agent = Agent.objects.filter(hubspot_owner_id=occurrence.closing_owner_id).first()
    closed = ClosedConversation(
        cycle=target,
        hubspot_ticket_id=occurrence.ticket_id,
        closed_at=occurrence.effective_at,
        closed_by_owner_id=occurrence.closing_owner_id,
        closed_by_agent_name=closing_agent.name if closing_agent else None,
    )
    if assigned is not None:
        for field in (
            "agent_id",
            "hubspot_owner_id",
            "agent_name",
            "pipeline_id",
            "entered_queue_at",
            "assigned_at",
            "queue_wait_seconds",
            "contact_name",
            "contact_email",
            "priority",
            "subject",
        ):
            setattr(closed, field, getattr(assigned, field))
        closed.total_handle_time_minutes = _minutes(assigned.assigned_at, occurrence.effective_at)
        closed.resolution_time_minutes = _minutes(assigned.entered_queue_at, occurrence.effective_at)
        if not closed.closed_by_agent_name and assigned.agent:
            closed.closed_by_agent_name = assigned.agent.name
        if occurrence.closing_owner_id and occurrence.closing_owner_id != assigned.hubspot_owner_id:
            closed.closure_source = "system"
        if current and assigned.agent and not capacity_enforced():
            decrement_agent_chat_count(assigned.agent)
    closed.save(force_insert=True)
    if assigned:
        assigned.delete()
    pending.delete()
    if target is not None:
        target.state = SupportConversationCycle.State.CLOSED
        target.closed_at = occurrence.effective_at
        target.save(update_fields=["state", "closed_at", "updated_at"])
    if current:
        _transition_lifecycle_best_effort(
            occurrence.ticket_id,
            ["RESOLVED_BY_HUMAN"],
            reason="Proven current support cycle closed.",
            source_event_id=occurrence.source_event_id,
            strict=True,
        )
        _transition_lifecycle_best_effort(
            occurrence.ticket_id,
            ["CLOSED"],
            reason="Proven current support cycle closed.",
            closed_at=occurrence.effective_at,
            source_event_id=occurrence.source_event_id,
            strict=True,
        )
