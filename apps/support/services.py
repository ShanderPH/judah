"""Business logic for support/helpdesk app."""

from __future__ import annotations

from uuid import UUID

import structlog
from django.utils import timezone

from apps.support.models import Ticket
from apps.support.schemas import CreateTicketRequest, UpdateTicketRequest
from common.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


def get_ticket(ticket_id: UUID | str) -> Ticket:
    """Fetch a ticket by primary key (UUID) or by external ``ticket_id``.

    Raises:
        NotFoundError: If no ticket with the given identifier exists.
    """
    try:
        return Ticket.objects.get(pk=ticket_id)
    except (Ticket.DoesNotExist, ValueError):
        try:
            return Ticket.objects.get(ticket_id=str(ticket_id))
        except Ticket.DoesNotExist as err:
            raise NotFoundError(f"Ticket with id={ticket_id} not found.") from err


def list_tickets(
    status: str | None = None,
    church: str | None = None,
    priority: str | None = None,
) -> list[Ticket]:
    """Return tickets filtered by optional status, church, and priority."""
    qs = Ticket.objects.all()
    if status:
        qs = qs.filter(status=status)
    if church:
        qs = qs.filter(ticket_church=church)
    if priority:
        qs = qs.filter(priority=priority)
    return list(qs.order_by("-created_at"))


def create_ticket(payload: CreateTicketRequest) -> Ticket:
    """Create a new support ticket."""
    ticket = Ticket.objects.create(
        ticket_id=payload.ticket_id,
        customer_name=payload.customer_name,
        ticket_church=payload.ticket_church,
        category=payload.category,
        priority=payload.priority,
        status=payload.status,
        affected_device=payload.affected_device,
        scope_of_impact=payload.scope_of_impact,
        affected_module=payload.affected_module,
        affected_functionality=payload.affected_functionality,
        created_at=payload.created_at or timezone.now(),
    )
    logger.info("ticket_created", ticket_id=str(ticket.pk), external_id=ticket.ticket_id)
    return ticket


def update_ticket(ticket_id: UUID | str, payload: UpdateTicketRequest) -> Ticket:
    """Partially update an existing ticket."""
    ticket = get_ticket(ticket_id)
    updated_fields: list[str] = []

    for field in (
        "status",
        "priority",
        "category",
        "affected_device",
        "scope_of_impact",
        "affected_module",
        "affected_functionality",
        "closed_at",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(ticket, field, value)
            updated_fields.append(field)

    if updated_fields:
        ticket.save(update_fields=[*updated_fields, "updated_at"])
        logger.info("ticket_updated", ticket_id=str(ticket.pk), fields=updated_fields)
    return ticket
