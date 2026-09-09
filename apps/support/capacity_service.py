"""Ticket-identified occupancy and durable reservation accounting.

Writers lock ticket, cycle, queue, operation, then agents in UUID order.
Provider reads must finish before entering this transaction boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.support.models import (
    Agent,
    AgentCapacityReservation,
    AssignmentAttempt,
    ConversationReassignment,
    NewConversation,
    SupportConversationCycle,
    SupportTicketOccupancy,
)


def capacity_mode() -> str:
    """Return a validated rollout mode; invalid configuration fails closed."""
    mode = str(getattr(settings, "SUPPORT_CAPACITY_MODE", "off"))
    if mode not in {"off", "shadow", "enforce"}:
        raise ValueError("Invalid SUPPORT_CAPACITY_MODE")
    return mode


def capacity_enforced() -> bool:
    """Whether all capacity decisions use identified occupancy."""
    return capacity_mode() == "enforce"


def capacity_account() -> str:
    """Require explicit provider account identity."""
    account = str(settings.HUBSPOT_PORTAL_ID).strip()
    if not account:
        raise ValueError("Capacity reconciliation requires HUBSPOT_PORTAL_ID")
    return account


@contextmanager
def ticket_transaction(ticket_id: str) -> Iterator[SupportTicketOccupancy]:
    """Serialize a ticket and its lifecycle before any operation/agent locks."""
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("capacity_reconcile")
    with transaction.atomic():
        occupancy, _ = SupportTicketOccupancy.objects.get_or_create(
            source_account_id=capacity_account(),
            hubspot_ticket_id=ticket_id,
        )
        occupancy = SupportTicketOccupancy.objects.select_for_update().get(pk=occupancy.pk)
        list(
            SupportConversationCycle.objects.select_for_update()
            .filter(
                hubspot_ticket_id=ticket_id,
            )
            .order_by("pk")
        )
        list(NewConversation.objects.select_for_update().filter(hubspot_ticket_id=ticket_id).order_by("pk"))
        yield occupancy


def capacity_count(agent_id: UUID) -> int:
    """Count the union of occupied and reserved ticket identities."""
    occupied = SupportTicketOccupancy.objects.filter(agent_id=agent_id, state="active").values_list("pk", flat=True)
    reserved = AgentCapacityReservation.objects.filter(agent_id=agent_id, state="held").values_list(
        "occupancy_id", flat=True
    )
    return len(set(occupied) | set(reserved))


def materialize(agent_ids: set[UUID]) -> None:
    """Project occupancy under stable agent locks without legacy deltas."""
    for agent in Agent.objects.select_for_update().filter(pk__in=agent_ids).order_by("pk"):
        agent.capacity_revision += 1
        fields = ["capacity_revision"]
        if capacity_enforced():
            agent.current_simultaneous_chats = capacity_count(agent.pk)
            fields.append("current_simultaneous_chats")
        agent.save(update_fields=fields)


def capacity_ready(agent: Agent) -> bool:
    """Check freshness and completeness again while holding the agent lock."""
    return (
        agent.capacity_state == "ready"
        and agent.capacity_reconciled_at is not None
        and agent.capacity_reconciled_at
        >= timezone.now() - timedelta(seconds=int(settings.SUPPORT_CAPACITY_FRESHNESS_SECONDS))
        and capacity_count(agent.pk) < (agent.max_simultaneous_chats if agent.max_simultaneous_chats is not None else 5)
    )


def hold_capacity(
    occupancy: SupportTicketOccupancy,
    agent: Agent,
    *,
    attempt: AssignmentAttempt | None = None,
    reassignment: ConversationReassignment | None = None,
) -> AgentCapacityReservation:
    """Hold once per operation; the caller owns ticket and agent locks."""
    key = f"attempt:{attempt.pk}" if attempt else f"reassignment:{reassignment.pk if reassignment else ''}"
    reservation, created = AgentCapacityReservation.objects.get_or_create(
        operation_key=key,
        defaults={
            "occupancy": occupancy,
            "agent": agent,
            "assignment_attempt": attempt,
            "reassignment": reassignment,
            "held_at": timezone.now(),
        },
    )
    if not created and reservation.state == "released":
        reservation.state = "held"
        reservation.held_at = timezone.now()
        reservation.concluded_at = None
        reservation.conclusion_reason = ""
        reservation.save(update_fields=["state", "held_at", "concluded_at", "conclusion_reason"])
    occupancy.revision += 1
    occupancy.save(update_fields=["revision"])
    materialize({agent.pk})
    return reservation


def conclude_reservation(reservation: AgentCapacityReservation, *, converted: bool, reason: str) -> None:
    """Conclude a held reservation exactly once under its ticket lock."""
    if reservation.state != "held":
        return
    reservation.state = "converted" if converted else "released"
    reservation.concluded_at = timezone.now()
    reservation.conclusion_reason = reason[:128]
    reservation.save(update_fields=["state", "concluded_at", "conclusion_reason"])


def degrade_agents(agent_ids: set[UUID]) -> None:
    """Invalidate readiness on unresolved provider evidence."""
    with transaction.atomic():
        for agent in Agent.objects.select_for_update().filter(pk__in=agent_ids).order_by("pk"):
            agent.capacity_state = "degraded"
            agent.capacity_revision += 1
            agent.save(update_fields=["capacity_state", "capacity_revision"])


@contextmanager
def assignment_transaction(attempt_id: UUID) -> Iterator[SupportTicketOccupancy | None]:
    """Acquire the canonical lock prefix for attempt state transitions."""
    if capacity_enforced():
        identity = AssignmentAttempt.objects.values_list("ticket_id", flat=True).get(pk=attempt_id)
        with ticket_transaction(identity) as occupancy:
            yield occupancy
    else:
        with transaction.atomic():
            yield None


@contextmanager
def optional_ticket_transaction(ticket_id: str) -> Iterator[SupportTicketOccupancy | None]:
    """Use ticket serialization only for the enforcing protocol."""
    if capacity_enforced():
        with ticket_transaction(ticket_id) as occupancy:
            yield occupancy
    else:
        with transaction.atomic():
            yield None
