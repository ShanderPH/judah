"""Persist provider lifecycle evidence before projecting support state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.support.models import SupportLifecycleOccurrence

if TYPE_CHECKING:
    from apps.support.conversation_cycle_service import CycleOpenResult
    from apps.support.ticket_close_service import TicketCloseOccurrence, TicketCloseResult


class InvalidOccurrenceEvidenceError(ValueError):
    """An observation lacks a provider-proven temporal identity."""


def _proven_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise InvalidOccurrenceEvidenceError("Occurrence timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _require_identity(account_id: str, ticket_id: str) -> None:
    if not account_id.strip() or not ticket_id.strip():
        raise InvalidOccurrenceEvidenceError("Occurrence requires account and ticket identities")


def _temporal_key(account_id: str, ticket_id: str, occurrence_type: str, occurred_at: datetime) -> str:
    return f"hubspot:{account_id}:{ticket_id}:{occurrence_type}:{occurred_at.isoformat()}"


def _pending_key(account_id: str, ticket_id: str, cycle_id: UUID | None) -> str:
    return f"hubspot:{account_id}:{ticket_id}:closed:pending:{cycle_id or 'unresolved'}"


def record_proven_occurrence(
    *,
    account_id: str,
    ticket_id: str,
    occurrence_type: SupportLifecycleOccurrence.Type,
    occurred_at: datetime,
    evidence_source: str,
    source_event_id: str = "",
    provider_updated_at: datetime | None = None,
    observation_id: str = "",
) -> SupportLifecycleOccurrence:
    """Deduplicate a provider-proven occurrence by ticket, type and time."""
    _require_identity(account_id, ticket_id)
    effective_at = _proven_time(occurred_at)
    key = _temporal_key(account_id, ticket_id, occurrence_type, effective_at)
    with transaction.atomic():
        existing = (
            SupportLifecycleOccurrence.objects.select_for_update()
            .filter(
                source_system="hubspot",
                source_account_id=account_id,
                hubspot_ticket_id=ticket_id,
                occurrence_type=occurrence_type,
                occurred_at=effective_at,
            )
            .first()
        )
        if existing:
            return existing
        if occurrence_type == SupportLifecycleOccurrence.Type.CLOSED:
            from apps.support.models import SupportConversationCycle
            from apps.support.ticket_close_service import TicketCloseOccurrence, resolve_close_target

            cycles = list(
                SupportConversationCycle.objects.filter(source_account_id=account_id, hubspot_ticket_id=ticket_id)
            )
            target = resolve_close_target(cycles, TicketCloseOccurrence(ticket_id, effective_at))
            pending = (
                SupportLifecycleOccurrence.objects.select_for_update()
                .filter(
                    evidence_key=_pending_key(account_id, ticket_id, target.cycle_id),
                    evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVIDER_MATERIALIZATION_PENDING,
                )
                .first()
            )
            if pending:
                try:
                    with transaction.atomic():
                        pending.occurred_at = effective_at
                        pending.evidence_status = SupportLifecycleOccurrence.EvidenceStatus.PROVEN
                        pending.evidence_source = evidence_source
                        pending.source_event_id = source_event_id
                        pending.provider_updated_at = provider_updated_at
                        pending.observation_id = observation_id[:128]
                        pending.next_reconcile_at = timezone.now() + timedelta(seconds=30)
                        pending.save(
                            update_fields=[
                                "occurred_at",
                                "evidence_status",
                                "evidence_source",
                                "source_event_id",
                                "provider_updated_at",
                                "observation_id",
                                "next_reconcile_at",
                                "updated_at",
                            ]
                        )
                except IntegrityError:
                    return SupportLifecycleOccurrence.objects.get(
                        source_system="hubspot",
                        source_account_id=account_id,
                        hubspot_ticket_id=ticket_id,
                        occurrence_type=occurrence_type,
                        occurred_at=effective_at,
                    )
                return pending
        try:
            with transaction.atomic():
                return SupportLifecycleOccurrence.objects.create(
                    source_account_id=account_id,
                    hubspot_ticket_id=ticket_id,
                    occurrence_type=occurrence_type,
                    occurred_at=effective_at,
                    evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVEN,
                    evidence_source=evidence_source,
                    evidence_key=key,
                    source_event_id=source_event_id,
                    provider_updated_at=provider_updated_at,
                    observation_id=observation_id[:128],
                    next_reconcile_at=(
                        timezone.now() + timedelta(seconds=30)
                        if occurrence_type == SupportLifecycleOccurrence.Type.CLOSED
                        else None
                    ),
                )
        except IntegrityError:
            return SupportLifecycleOccurrence.objects.get(
                source_system="hubspot",
                source_account_id=account_id,
                hubspot_ticket_id=ticket_id,
                occurrence_type=occurrence_type,
                occurred_at=effective_at,
            )


def record_pending_close(
    *,
    account_id: str,
    ticket_id: str,
    cycle_id: UUID | None,
    provider_updated_at: datetime | None,
    observation_id: str = "",
    schedule: bool = True,
) -> SupportLifecycleOccurrence:
    """Keep a closed-stage observation pending until its timestamp materializes."""
    _require_identity(account_id, ticket_id)
    key = _pending_key(account_id, ticket_id, cycle_id)
    with transaction.atomic():
        occurrence, created = SupportLifecycleOccurrence.objects.get_or_create(
            evidence_key=key,
            defaults={
                "source_account_id": account_id,
                "hubspot_ticket_id": ticket_id,
                "occurrence_type": SupportLifecycleOccurrence.Type.CLOSED,
                "evidence_status": SupportLifecycleOccurrence.EvidenceStatus.PROVIDER_MATERIALIZATION_PENDING,
                "evidence_source": "crm_readback",
                "provider_updated_at": provider_updated_at,
                "observation_id": observation_id[:128],
                "next_reconcile_at": timezone.now() + timedelta(seconds=30),
            },
        )
        if created and schedule:
            from apps.support.tasks import task_reconcile_lifecycle_occurrence

            transaction.on_commit(
                lambda: task_reconcile_lifecycle_occurrence.apply_async(args=[str(occurrence.pk)], countdown=30)
            )
        return occurrence


def mark_processed(occurrence_id: UUID) -> None:
    """Record that a proven occurrence reached its canonical projection."""
    SupportLifecycleOccurrence.objects.filter(
        pk=occurrence_id,
        evidence_status=SupportLifecycleOccurrence.EvidenceStatus.PROVEN,
    ).update(processing_status=SupportLifecycleOccurrence.ProcessingStatus.PROCESSED, next_reconcile_at=None)


def owner_occurrence_matches_cycle(occurrence: SupportLifecycleOccurrence, cycle_id: UUID | None) -> bool:
    """Accept owner evidence only within a proven cycle's temporal interval."""
    if cycle_id is None or occurrence.occurred_at is None:
        return False
    from apps.support.models import SupportConversationCycle

    return (
        SupportConversationCycle.objects.filter(
            pk=cycle_id,
            source_account_id=occurrence.source_account_id,
            hubspot_ticket_id=occurrence.hubspot_ticket_id,
            entered_stage_at__lte=occurrence.occurred_at,
        )
        .filter(Q(closed_at__isnull=True) | Q(closed_at__gte=occurrence.occurred_at))
        .exists()
    )


def open_from_proven_occurrence(
    *,
    ticket_id: str,
    entered_at: datetime,
    account_id: str,
    evidence_source: str,
    source_event_id: str = "",
    observation_id: str = "",
) -> CycleOpenResult:
    """Persist provider queue entry and materialize its cycle exactly once."""
    from apps.support.conversation_cycle_service import CycleClassification, open_or_get_cycle

    with transaction.atomic():
        occurrence = record_proven_occurrence(
            account_id=account_id,
            ticket_id=ticket_id,
            occurrence_type=SupportLifecycleOccurrence.Type.ENTERED_SUPPORT_QUEUE,
            occurred_at=entered_at,
            evidence_source=evidence_source,
            source_event_id=source_event_id,
            observation_id=observation_id,
        )
        result = open_or_get_cycle(
            hubspot_ticket_id=ticket_id,
            entered_stage_value=entered_at,
            source_account_id=account_id,
            source_event_id=source_event_id,
        )
        if result.admission.classification in {CycleClassification.CREATED, CycleClassification.DUPLICATE}:
            mark_processed(occurrence.pk)
        return result


def project_close_occurrence(occurrence: TicketCloseOccurrence) -> TicketCloseResult:
    """Persist a proven close before invoking the canonical close projection."""
    from django.conf import settings

    from apps.support.ticket_close_service import CloseClassification, reconcile_close_occurrence

    if settings.HUBSPOT_PROVIDER_CONTRACT_MODE == "off":
        return reconcile_close_occurrence(occurrence, allow_legacy=not settings.CONVERSATION_CYCLES_ENFORCED)

    proven = record_proven_occurrence(
        account_id=str(settings.HUBSPOT_PORTAL_ID),
        ticket_id=occurrence.ticket_id,
        occurrence_type=SupportLifecycleOccurrence.Type.CLOSED,
        occurred_at=occurrence.effective_at,
        evidence_source="webhook_property",
        source_event_id=occurrence.source_event_id,
    )
    result = reconcile_close_occurrence(occurrence, allow_legacy=not settings.CONVERSATION_CYCLES_ENFORCED)
    if result.classification in {
        CloseClassification.APPLIED_CURRENT,
        CloseClassification.APPLIED_HISTORICAL,
        CloseClassification.DUPLICATE,
    }:
        mark_processed(proven.pk)
    return result
