"""Django Ninja API endpoints for support."""

from ninja import Router

from apps.support.models import Ticket
from apps.support.schemas import CreateTicketRequest, TicketListResponse, TicketResponse, UpdateTicketRequest
from apps.support.services import create_ticket, get_ticket, list_tickets, update_ticket
from common.pagination import StandardPagination, paginate

router = Router()


@router.get("/tickets/", response=list[TicketListResponse], summary="List tickets")
@paginate(StandardPagination)
def list_tickets_endpoint(
    request,
    status: str | None = None,
    queue: str | None = None,
    priority: str | None = None,
) -> list[Ticket]:
    """Return paginated tickets with optional filters."""
    return list_tickets(status=status, queue_slug=queue, priority=priority)


@router.post("/tickets/", response={201: TicketResponse}, summary="Create ticket")
def create_ticket_endpoint(request, payload: CreateTicketRequest) -> tuple[int, Ticket]:
    """Create a new support ticket."""
    return 201, create_ticket(payload)


@router.get("/tickets/{ticket_id}", response=TicketResponse, summary="Get ticket")
def get_ticket_endpoint(request, ticket_id: int) -> Ticket:
    """Return a single ticket by ID."""
    return get_ticket(ticket_id)


@router.patch("/tickets/{ticket_id}", response=TicketResponse, summary="Update ticket")
def update_ticket_endpoint(request, ticket_id: int, payload: UpdateTicketRequest) -> Ticket:
    """Partially update a ticket."""
    return update_ticket(ticket_id, payload)
