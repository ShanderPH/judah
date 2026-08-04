"""Transactional service-cycle identity for reopened conversations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.ai_agents.models import ConversationInstance, ConversationServiceCycle

_CYCLE_NAMESPACE = uuid.UUID("4fce6f5d-2574-5d5f-8edb-1fa7e0f441e2")
_TERMINAL_STATES = {
    ConversationInstance.State.CLOSED,
    ConversationInstance.State.FAILED_TERMINAL,
    ConversationInstance.State.IGNORED,
}


@dataclass(frozen=True)
class ServiceCycleContext:
    """Typed context exposed to metrics and the Salomão Supervisor."""

    cycle_id: str
    idempotency_key: str
    sequence: int
    is_reopened: bool
    reopen_count: int
    opened_from_state: str | None
    opened_reason: str

    def as_dict(self) -> dict[str, str | int | bool | None]:
        """Return a JSON-safe representation for agent contracts."""
        return {
            "service_cycle_id": self.cycle_id,
            "service_cycle_idempotency_key": self.idempotency_key,
            "attendance_sequence": self.sequence,
            "is_reopened": self.is_reopened,
            "reopen_count": self.reopen_count,
            "reopened_from_state": self.opened_from_state,
            "reopen_reason": self.opened_reason,
        }


def _idempotency_key(instance_id: uuid.UUID, sequence: int) -> uuid.UUID:
    """Derive a stable, unique key for one instance attendance sequence."""
    return uuid.uuid5(_CYCLE_NAMESPACE, f"judah:conversation:{instance_id}:service-cycle:{sequence}")


def _create_cycle(
    instance: ConversationInstance,
    *,
    sequence: int,
    status: str,
    opened_at: datetime,
    opened_from_state: str = "",
    opened_reason: str = "",
    opened_by_event_id: str = "",
    closed_at: datetime | None = None,
    closed_reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> ConversationServiceCycle:
    return ConversationServiceCycle.objects.create(
        instance=instance,
        sequence=sequence,
        idempotency_key=_idempotency_key(instance.pk, sequence),
        status=status,
        opened_at=opened_at,
        closed_at=closed_at,
        opened_from_state=opened_from_state,
        opened_reason=opened_reason,
        opened_by_event_id=opened_by_event_id,
        closed_reason=closed_reason,
        metadata=metadata or {},
    )


def _bootstrap_legacy_cycle(instance: ConversationInstance) -> ConversationServiceCycle:
    """Create the first historical cycle for an instance created before this schema."""
    now = timezone.now()
    is_terminal = instance.state in _TERMINAL_STATES
    return _create_cycle(
        instance,
        sequence=1,
        status=(ConversationServiceCycle.Status.CLOSED if is_terminal else ConversationServiceCycle.Status.OPEN),
        opened_at=instance.opened_at or instance.created_at or now,
        closed_at=(instance.closed_at or now) if is_terminal else None,
        opened_reason="Legacy conversation instance adopted by service-cycle tracking.",
        closed_reason="Legacy terminal state adopted by service-cycle tracking." if is_terminal else "",
        metadata={"identity_source": "legacy_instance_bootstrap"},
    )


@transaction.atomic
def ensure_current_service_cycle(instance: ConversationInstance) -> ConversationServiceCycle:
    """Return the effective cycle, repairing a missing legacy projection safely."""
    locked = ConversationInstance.objects.select_for_update().get(pk=instance.pk)
    open_cycle = (
        ConversationServiceCycle.objects.select_for_update()
        .filter(instance=locked, status=ConversationServiceCycle.Status.OPEN)
        .first()
    )
    if open_cycle is not None:
        return open_cycle

    latest = ConversationServiceCycle.objects.select_for_update().filter(instance=locked).order_by("-sequence").first()
    if latest is None:
        return _bootstrap_legacy_cycle(locked)
    if locked.state in _TERMINAL_STATES:
        return latest

    sequence = latest.sequence + 1
    return _create_cycle(
        locked,
        sequence=sequence,
        status=ConversationServiceCycle.Status.OPEN,
        opened_at=timezone.now(),
        opened_from_state=latest.opened_from_state,
        opened_reason="Recovered an open lifecycle state without an active service cycle.",
        metadata={"identity_source": "state_cycle_reconciliation"},
    )


@transaction.atomic
def reopen_service_cycle(
    instance: ConversationInstance,
    *,
    from_state: str,
    reason: str,
    source_event_id: str = "",
) -> ConversationServiceCycle:
    """Close the previous attendance and create exactly one new open cycle."""
    locked = ConversationInstance.objects.select_for_update().get(pk=instance.pk)
    cycles = ConversationServiceCycle.objects.select_for_update().filter(instance=locked)
    latest = cycles.order_by("-sequence").first()
    if latest is None:
        latest = _bootstrap_legacy_cycle(locked)

    open_cycle = cycles.filter(status=ConversationServiceCycle.Status.OPEN).first()
    now = timezone.now()
    if open_cycle is not None:
        open_cycle.status = ConversationServiceCycle.Status.CLOSED
        open_cycle.closed_at = open_cycle.closed_at or now
        open_cycle.closed_reason = open_cycle.closed_reason or "Superseded by a verified conversation reopening."
        open_cycle.save(update_fields=["status", "closed_at", "closed_reason", "updated_at"])

    latest = cycles.order_by("-sequence").first() or latest
    sequence = latest.sequence + 1
    return _create_cycle(
        locked,
        sequence=sequence,
        status=ConversationServiceCycle.Status.OPEN,
        opened_at=now,
        opened_from_state=from_state,
        opened_reason=reason,
        opened_by_event_id=source_event_id,
        metadata={
            "identity_source": "verified_reopen",
            "previous_cycle_id": str(latest.pk),
            "previous_cycle_idempotency_key": str(latest.idempotency_key),
        },
    )


@transaction.atomic
def close_current_service_cycle(
    instance: ConversationInstance,
    *,
    reason: str,
) -> ConversationServiceCycle:
    """Close the current cycle idempotently and return the effective cycle."""
    locked = ConversationInstance.objects.select_for_update().get(pk=instance.pk)
    cycle = (
        ConversationServiceCycle.objects.select_for_update()
        .filter(instance=locked, status=ConversationServiceCycle.Status.OPEN)
        .first()
    )
    if cycle is None:
        cycle = ensure_current_service_cycle(locked)
    if cycle.status == ConversationServiceCycle.Status.CLOSED:
        return cycle
    cycle.status = ConversationServiceCycle.Status.CLOSED
    cycle.closed_at = timezone.now()
    cycle.closed_reason = reason
    cycle.save(update_fields=["status", "closed_at", "closed_reason", "updated_at"])
    return cycle


def service_cycle_context(instance: ConversationInstance) -> ServiceCycleContext:
    """Return the current/latest cycle as typed Supervisor context."""
    cycle = ensure_current_service_cycle(instance)
    return ServiceCycleContext(
        cycle_id=str(cycle.pk),
        idempotency_key=str(cycle.idempotency_key),
        sequence=cycle.sequence,
        is_reopened=cycle.sequence > 1,
        reopen_count=max(cycle.sequence - 1, 0),
        opened_from_state=cycle.opened_from_state or None,
        opened_reason=cycle.opened_reason,
    )


__all__ = [
    "ServiceCycleContext",
    "close_current_service_cycle",
    "ensure_current_service_cycle",
    "reopen_service_cycle",
    "service_cycle_context",
]
