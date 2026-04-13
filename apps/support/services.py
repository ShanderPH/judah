"""Business logic for support/helpdesk app."""

import contextlib

import structlog

from apps.support.models import Queue, Ticket
from apps.support.schemas import CreateTicketRequest, UpdateTicketRequest
from common.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


def get_ticket(ticket_id: int) -> Ticket:
    """Fetch a ticket by primary key.

    Raises:
        NotFoundError: If no ticket with the given ID exists.
    """
    try:
        return Ticket.objects.select_related("queue", "sla", "assigned_to").get(pk=ticket_id)
    except Ticket.DoesNotExist as err:
        raise NotFoundError(f"Ticket with id={ticket_id} not found.") from err


def list_tickets(
    status: str | None = None,
    queue_slug: str | None = None,
    priority: str | None = None,
) -> list[Ticket]:
    """Return tickets filtered by optional status, queue slug, and priority."""
    qs = Ticket.objects.select_related("queue", "assigned_to")
    if status:
        qs = qs.filter(status=status)
    if queue_slug:
        qs = qs.filter(queue__slug=queue_slug)
    if priority:
        qs = qs.filter(priority=priority)
    return list(qs.order_by("-created_at"))


def create_ticket(payload: CreateTicketRequest) -> Ticket:
    """Create a new support ticket.

    Args:
        payload: Validated ticket creation data.

    Returns:
        The newly created Ticket instance.
    """
    queue = None
    if payload.queue_id:
        with contextlib.suppress(Queue.DoesNotExist):
            queue = Queue.objects.get(pk=payload.queue_id)

    ticket = Ticket.objects.create(
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
        channel=payload.channel,
        customer_email=payload.customer_email,
        customer_name=payload.customer_name,
        church_external_id=payload.church_external_id,
        queue=queue,
    )
    logger.info("ticket_created", ticket_id=ticket.pk, subject=ticket.subject)
    return ticket


def update_ticket(ticket_id: int, payload: UpdateTicketRequest) -> Ticket:
    """Partially update an existing ticket.

    Raises:
        NotFoundError: If the ticket does not exist.
    """
    ticket = get_ticket(ticket_id)
    updated_fields: list[str] = []

    if payload.status is not None:
        ticket.status = payload.status
        updated_fields.append("status")
    if payload.priority is not None:
        ticket.priority = payload.priority
        updated_fields.append("priority")
    if payload.queue_id is not None:
        try:
            ticket.queue = Queue.objects.get(pk=payload.queue_id)
            updated_fields.append("queue")
        except Queue.DoesNotExist:
            pass

    if updated_fields:
        ticket.save(update_fields=[*updated_fields, "updated_at"])
        logger.info("ticket_updated", ticket_id=ticket.pk, fields=updated_fields)
    return ticket
