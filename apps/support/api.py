"""Django Ninja API endpoints for support."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ninja import Router

from apps.support.schemas import (
    AssignedConversationResponse,
    CreateTicketRequest,
    NewConversationResponse,
    QueueHealthResponse,
    QueueMetricsResponse,
    QueueStatusResponse,
    SyncNovoResponse,
    TicketListResponse,
    TicketResponse,
    UpdateTicketRequest,
)
from apps.support.services import create_ticket, get_ticket, list_tickets, update_ticket
from common.pagination import StandardPagination, paginate

if TYPE_CHECKING:
    from apps.support.models import AssignedConversation, NewConversation, QueuePerformanceMetrics, Ticket

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


# ---------------------------------------------------------------------------
# Auto-assignment queue endpoints
# ---------------------------------------------------------------------------


@router.get("/queue/status/", response=QueueStatusResponse, summary="Queue status snapshot")
def get_queue_status(request) -> dict:
    """Return the current assignment queue status (online agents, eligibility, queue depth)."""
    from apps.support.queue_service import get_queue_status

    return get_queue_status()


@router.get(
    "/queue/pending/",
    response=list[NewConversationResponse],
    summary="List pending (unassigned) conversations",
)
@paginate(StandardPagination)
def list_pending_conversations(request) -> list[NewConversation]:
    """Return tickets currently waiting in the assignment queue."""
    from apps.support.models import NewConversation

    return NewConversation.objects.order_by("entered_queue_at")


@router.get(
    "/queue/assigned/",
    response=list[AssignedConversationResponse],
    summary="List assigned conversations",
)
@paginate(StandardPagination)
def list_assigned_conversations(
    request,
    agent_owner_id: int | None = None,
    closed: bool | None = None,
) -> list[AssignedConversation]:
    """Return conversations assigned by the auto-assignment system.

    Query params:
    - ``agent_owner_id``: filter by HubSpot owner ID.
    - ``closed``: True = only closed, False = only open, omit = all.
    """
    from apps.support.models import AssignedConversation

    qs = AssignedConversation.objects.select_related("agent").order_by("-assigned_at")
    if agent_owner_id is not None:
        qs = qs.filter(hubspot_owner_id=agent_owner_id)
    if closed is True:
        qs = qs.filter(closed_at__isnull=False)
    elif closed is False:
        qs = qs.filter(closed_at__isnull=True)
    return qs


@router.get(
    "/queue/health/",
    response=QueueHealthResponse,
    summary="Auto-assignment system health check",
)
def get_queue_health(request) -> dict:
    """Return a full diagnostic snapshot of the auto-assignment system.

    Includes:
    - Summary counts (online, eligible, away, queue depth)
    - List of absent agents (AWAY/OFFLINE) currently excluded from the queue
    - List of eligible agents with their current load
    - Tickets waiting in the assignment queue
    - Last 5 assignment log entries
    - ``system_ok`` flag and human-readable issue/warning list
    """
    from django.utils import timezone

    from apps.support.models import Agent, AssignmentLog, NewConversation
    from apps.support.queue_service import get_eligible_agents, get_last_assigned_owner_id

    all_agents = list(Agent.objects.order_by("status_enum", "name"))
    eligible_objs = get_eligible_agents()
    eligible_ids = {a.pk for a in eligible_objs}
    last_owner = get_last_assigned_owner_id()

    def _build_agent(a: Agent) -> dict:
        at_capacity = a.current_simultaneous_chats >= (a.max_simultaneous_chats or 5)
        return {
            "id": str(a.id),
            "name": a.name,
            "email": a.agent_email,
            "hubspot_owner_id": a.hubspot_owner_id,
            "status": a.status_enum or "offline",
            "current_chats": int(a.current_simultaneous_chats),
            "max_chats": a.max_simultaneous_chats or 5,
            "eligible": a.pk in eligible_ids,
            "at_capacity": at_capacity,
            "auto_assign_enabled": a.auto_assign_enabled,
            "last_assignment_at": a.last_assignment_at,
            "is_last_assigned": a.hubspot_owner_id == last_owner,
        }

    absent = [a for a in all_agents if (a.status_enum or "offline") in ("away", "offline", "busy")]
    online_count = sum(1 for a in all_agents if a.status_enum == "online")

    pending_qs = NewConversation.objects.order_by("entered_queue_at")
    now = timezone.now()
    pending_tickets = [
        {
            "hubspot_ticket_id": c.hubspot_ticket_id,
            "priority": c.priority,
            "contact_name": c.contact_name,
            "entered_queue_at": c.entered_queue_at,
            "wait_seconds": round((now - c.entered_queue_at).total_seconds(), 1),
        }
        for c in pending_qs
    ]

    logs_qs = AssignmentLog.objects.order_by("-assigned_at")[:5]
    last_assignments = [
        {
            "ticket_id": lg.ticket_id,
            "agent_name": lg.agent_name,
            "hubspot_owner_id": lg.hubspot_owner_id,
            "assignment_type": lg.assignment_type,
            "queue_wait_seconds": float(lg.queue_wait_seconds) if lg.queue_wait_seconds else None,
            "assigned_at": lg.assigned_at,
        }
        for lg in logs_qs
    ]

    # Build issues / warnings
    issues: list[str] = []
    warnings: list[str] = []

    if not eligible_objs:
        issues.append("Nenhum agente elegível disponível — atribuições bloqueadas")
    elif len(eligible_objs) == 1:
        warnings.append(f"Apenas 1 agente elegível ({eligible_objs[0].name}) — regra 2 desativada")

    if pending_tickets:
        issues.append(f"{len(pending_tickets)} ticket(s) aguardando na fila sem agente disponível")

    away_with_chats = [a for a in absent if a.current_simultaneous_chats > 0]
    if away_with_chats:
        names = ", ".join(a.name for a in away_with_chats)
        warnings.append(f"Agentes ausentes com chats abertos: {names}")

    return {
        "timestamp": now,
        "summary": {
            "total_agents": len(all_agents),
            "online_agents": online_count,
            "away_agents": len(absent),
            "eligible_agents": len(eligible_objs),
            "pending_queue_depth": len(pending_tickets),
            "system_ok": len(issues) == 0,
            "warnings": warnings,
            "issues": issues,
        },
        "absent_agents": [
            {
                "name": a.name,
                "hubspot_owner_id": a.hubspot_owner_id,
                "status": a.status_enum or "offline",
                "open_chats": int(a.current_simultaneous_chats),
            }
            for a in absent
        ],
        "eligible_agents": [_build_agent(a) for a in eligible_objs],
        "pending_tickets": pending_tickets,
        "last_assignments": last_assignments,
    }


@router.post(
    "/queue/sync-novo/",
    response={202: SyncNovoResponse},
    summary="Sync NOVO-stage tickets from HubSpot into the internal queue",
    auth=None,
)
def sync_novo_tickets(request) -> tuple[int, dict]:
    """Fetch all tickets currently in the NOVO stage (939275049) from HubSpot
    and enqueue any that are not yet tracked in ``new_conversations``.

    Does NOT perform any assignment — tickets will be picked up automatically
    once an eligible agent comes online.

    Intended for manual trigger from an admin frontend or for backfilling after
    a downtime window where webhooks were missed.
    """
    from apps.support.auto_assign_service import sync_novo_stage_tickets

    sync_result = sync_novo_stage_tickets()
    return 202, {
        **sync_result,
        "queued_for_assignment": sync_result["created"] > 0,
    }


@router.get(
    "/queue/metrics/",
    response=list[QueueMetricsResponse],
    summary="Queue performance metrics",
)
@paginate(StandardPagination)
def list_queue_metrics(
    request,
    days: int = 30,
) -> list[QueuePerformanceMetrics]:
    """Return daily queue performance metrics for the last N days (default 30).

    Query params:
    - ``days``: number of past days to include (max 365).
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.support.models import QueuePerformanceMetrics

    cutoff = timezone.localdate() - timedelta(days=min(days, 365))
    return QueuePerformanceMetrics.objects.filter(metric_date__gte=cutoff).order_by("-metric_date")
