"""Administrative endpoints for the support domain.

Includes:
- Agent CRUD + capacity management.
- Public reads for AgentMetrics, AgentDailyTimeLog, and ConversationReassignment.
- Manual / forced assignment actions for admins.

All endpoints require admin or manager role and reuse the global JWT auth
configured on the parent ``NinjaAPI`` instance.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from ninja import Router

from apps.support.models import (
    Agent,
    AgentDailyTimeLog,
    AgentMetrics,
    AssignedConversation,
    AssignmentLog,
    ConversationReassignment,
    NewConversation,
)
from apps.support.queue_service import (
    decrement_agent_chat_count,
    increment_agent_chat_count,
)
from apps.support.schemas import (
    AgentDailyTimeLogResponse,
    AgentMetricsResponse,
    AgentMetricsSummary,
    AgentResponse,
    AssignmentActionResponse,
    ConversationReassignmentResponse,
    CreateAgentRequest,
    ForceReassignRequest,
    ManualAssignRequest,
    ReassignmentSummary,
    UpdateAgentRequest,
)
from common.exceptions import ConflictError, NotFoundError, ValidationError
from common.pagination import StandardPagination, paginate
from common.permissions import require_manager_or_admin

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Agents CRUD
# ---------------------------------------------------------------------------


@router.get("/agents/", response=list[AgentResponse], summary="List agents")
@paginate(StandardPagination)
def list_agents(
    request,
    status: str | None = None,
    team: str | None = None,
    is_active: bool | None = None,
) -> list[Agent]:
    """List support agents with optional status / team / active filters."""
    qs = Agent.objects.all()
    if status:
        qs = qs.filter(status_enum=status)
    if team:
        qs = qs.filter(team=team)
    if is_active is True:
        qs = qs.filter(Q(is_active=True) | Q(is_active__isnull=True))
    elif is_active is False:
        qs = qs.filter(is_active=False)
    return qs.order_by("name")


@router.get("/agents/{agent_id}", response=AgentResponse, summary="Retrieve a single agent")
def retrieve_agent(request, agent_id: str) -> Agent:
    """Return a single agent by primary key."""
    try:
        return Agent.objects.get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err


@router.post("/agents/", response={201: AgentResponse}, summary="Create agent")
@require_manager_or_admin
def create_agent(request, payload: CreateAgentRequest) -> tuple[int, Agent]:
    """Register a new support agent.

    The HubSpot owner ID and email must be unique. Newly created agents
    start in OFFLINE status with the SAT system controlling availability
    transitions afterwards.
    """
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_create_agent")
    if Agent.objects.filter(hubspot_owner_id=payload.hubspot_owner_id).exists():
        raise ConflictError(f"Agent with hubspot_owner_id={payload.hubspot_owner_id} already exists.")
    if Agent.objects.filter(agent_email__iexact=payload.agent_email).exists():
        raise ConflictError(f"Agent with email '{payload.agent_email}' already exists.")

    agent = Agent.objects.create(
        name=payload.name,
        agent_email=payload.agent_email,
        hubspot_owner_id=payload.hubspot_owner_id,
        team=payload.team,
        manager_email=payload.manager_email,
        timezone=payload.timezone,
        max_simultaneous_chats=payload.max_simultaneous_chats,
        auto_assign_enabled=payload.auto_assign_enabled,
        status_enum=Agent.StatusEnum.OFFLINE,
        is_active=True,
    )
    logger.info("agent_created", agent_id=str(agent.id), email=agent.agent_email)
    return 201, agent


@router.patch("/agents/{agent_id}", response=AgentResponse, summary="Update agent")
@require_manager_or_admin
def update_agent(request, agent_id: str, payload: UpdateAgentRequest) -> Agent:
    """Partially update an agent (capacity, schedule flags, activation)."""
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_update_agent")
    try:
        agent = Agent.objects.get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err

    updated_fields: list[str] = []
    if payload.name is not None:
        agent.name = payload.name
        updated_fields.append("name")
    if payload.team is not None:
        agent.team = payload.team
        updated_fields.append("team")
    if payload.manager_email is not None:
        agent.manager_email = payload.manager_email
        updated_fields.append("manager_email")
    if payload.timezone is not None:
        agent.timezone = payload.timezone
        updated_fields.append("timezone")
    if payload.max_simultaneous_chats is not None:
        agent.max_simultaneous_chats = payload.max_simultaneous_chats
        updated_fields.append("max_simultaneous_chats")
    if payload.auto_assign_enabled is not None:
        agent.auto_assign_enabled = payload.auto_assign_enabled
        updated_fields.append("auto_assign_enabled")
    if payload.is_active is not None:
        agent.is_active = payload.is_active
        updated_fields.append("is_active")
    if updated_fields:
        agent.updated_at = timezone.now()
        agent.save(update_fields=[*updated_fields, "updated_at"])
        logger.info("agent_updated", agent_id=str(agent.id), fields=updated_fields)
    return agent


@router.post(
    "/agents/{agent_id}/inactivate",
    response=AgentResponse,
    summary="Inactivate an agent (soft disable)",
)
@require_manager_or_admin
def inactivate_agent(request, agent_id: str) -> Agent:
    """Mark an agent as inactive and turn off auto-assignment.

    The record is preserved (soft delete) so that historical assignments
    remain auditable. A new agent with the same email/owner cannot be
    re-created until the previous record is reactivated.
    """
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_inactivate_agent")
    try:
        agent = Agent.objects.get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err

    agent.is_active = False
    agent.auto_assign_enabled = False
    agent.updated_at = timezone.now()
    agent.save(update_fields=["is_active", "auto_assign_enabled", "updated_at"])
    logger.info("agent_inactivated", agent_id=str(agent.id))
    return agent


@router.post(
    "/agents/{agent_id}/reactivate",
    response=AgentResponse,
    summary="Reactivate an inactive agent",
)
@require_manager_or_admin
def reactivate_agent(request, agent_id: str) -> Agent:
    """Reactivate a previously disabled agent."""
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_reactivate_agent")
    try:
        agent = Agent.objects.get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err

    agent.is_active = True
    agent.updated_at = timezone.now()
    agent.save(update_fields=["is_active", "updated_at"])
    logger.info("agent_reactivated", agent_id=str(agent.id))
    return agent


# ---------------------------------------------------------------------------
# Agent metrics / daily time logs / reassignments
# ---------------------------------------------------------------------------


@router.get(
    "/agents/{agent_id}/metrics/",
    response=list[AgentMetricsResponse],
    summary="Per-agent aggregated metrics",
)
@paginate(StandardPagination)
def list_agent_metrics(request, agent_id: str) -> list[AgentMetrics]:
    """Return historical metric snapshots for a specific agent."""
    try:
        agent = Agent.objects.only("hubspot_owner_id").get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err

    return AgentMetrics.objects.filter(agent_id=agent.hubspot_owner_id).order_by("-last_time_updated")


@router.get(
    "/metrics/agents/",
    response=list[AgentMetricsResponse],
    summary="List agent metric snapshots across the org",
)
@paginate(StandardPagination)
def list_all_agent_metrics(
    request,
    days: int = 30,
) -> list[AgentMetrics]:
    """List the most recent agent metric snapshots within the period."""
    cutoff = timezone.now() - timedelta(days=min(days, 365))
    return AgentMetrics.objects.filter(last_time_updated__gte=cutoff).order_by("-last_time_updated")


@router.get(
    "/metrics/agents/summary/",
    response=AgentMetricsSummary,
    summary="High-level aggregation of agent metrics",
)
def agent_metrics_summary(request, days: int = 30) -> dict:
    """Aggregate the most recent snapshots into a single dashboard payload."""
    cutoff = timezone.now() - timedelta(days=min(days, 365))
    rows = list(AgentMetrics.objects.filter(last_time_updated__gte=cutoff))

    total_chats = sum(r.total_chats for r in rows)
    chats_closed = sum(r.chats_closed for r in rows)
    handle_times = [float(r.average_ticket_time_min) for r in rows if r.average_ticket_time_min]
    first_responses = [float(r.first_response_time_avg_min) for r in rows if r.first_response_time_avg_min is not None]
    resolution_rates = [float(r.resolution_rate) for r in rows if r.resolution_rate is not None]
    csats = [float(r.customer_satisfaction_avg) for r in rows if r.customer_satisfaction_avg is not None]

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "period_days": min(days, 365),
        "total_agents_with_data": len({r.agent_id for r in rows}),
        "total_chats": total_chats,
        "total_chats_closed": chats_closed,
        "avg_handle_time_min": _avg(handle_times),
        "avg_first_response_min": _avg(first_responses),
        "avg_resolution_rate": _avg(resolution_rates),
        "avg_csat": _avg(csats),
    }


@router.get(
    "/agents/{agent_id}/time-logs/",
    response=list[AgentDailyTimeLogResponse],
    summary="Daily online/away time per agent",
)
@paginate(StandardPagination)
def list_agent_time_logs(request, agent_id: str, days: int = 30) -> list[AgentDailyTimeLog]:
    """Return daily SAT counters for an agent within the last ``days`` days."""
    try:
        agent = Agent.objects.get(pk=agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={agent_id} not found.") from err

    cutoff = timezone.localdate() - timedelta(days=min(days, 365))
    return AgentDailyTimeLog.objects.filter(agent=agent, log_date__gte=cutoff).order_by("-log_date")


@router.get(
    "/time-logs/",
    response=list[AgentDailyTimeLogResponse],
    summary="Daily time logs across all agents",
)
@paginate(StandardPagination)
def list_time_logs(request, days: int = 7) -> list[AgentDailyTimeLog]:
    """Return daily SAT counters across all agents in the window."""
    cutoff = timezone.localdate() - timedelta(days=min(days, 90))
    return AgentDailyTimeLog.objects.filter(log_date__gte=cutoff).order_by("-log_date", "agent__name")


@router.get(
    "/reassignments/",
    response=list[ConversationReassignmentResponse],
    summary="List ticket reassignment events",
)
@paginate(StandardPagination)
def list_reassignments(
    request,
    agent_owner_id: int | None = None,
    days: int = 30,
) -> list[ConversationReassignment]:
    """Return reassignments within ``days`` days, optionally filtered by agent."""
    cutoff = timezone.now() - timedelta(days=min(days, 365))
    qs = ConversationReassignment.objects.filter(reassigned_at__gte=cutoff)
    if agent_owner_id is not None:
        qs = qs.filter(Q(from_hubspot_owner_id=agent_owner_id) | Q(to_hubspot_owner_id=agent_owner_id))
    return qs.order_by("-reassigned_at")


@router.get(
    "/reassignments/summary/",
    response=list[ReassignmentSummary],
    summary="Net reassignment counts by agent",
)
def reassignments_summary(request, days: int = 30) -> list[dict]:
    """Aggregate transfers in/out by agent over the window."""
    cutoff = timezone.now() - timedelta(days=min(days, 365))
    incoming = (
        ConversationReassignment.objects.filter(
            reassigned_at__gte=cutoff,
            to_hubspot_owner_id__isnull=False,
        )
        .values("to_hubspot_owner_id", "to_agent_name")
        .annotate(count=Count("id"))
    )
    outgoing = (
        ConversationReassignment.objects.filter(
            reassigned_at__gte=cutoff,
            from_hubspot_owner_id__isnull=False,
        )
        .values("from_hubspot_owner_id", "from_agent_name")
        .annotate(count=Count("id"))
    )

    summary: dict[int, dict] = {}
    for row in incoming:
        owner_id = int(row["to_hubspot_owner_id"])
        summary.setdefault(
            owner_id,
            {
                "hubspot_owner_id": owner_id,
                "agent_name": row.get("to_agent_name"),
                "transferred_in": 0,
                "transferred_out": 0,
            },
        )
        summary[owner_id]["transferred_in"] = row["count"]
    for row in outgoing:
        owner_id = int(row["from_hubspot_owner_id"])
        summary.setdefault(
            owner_id,
            {
                "hubspot_owner_id": owner_id,
                "agent_name": row.get("from_agent_name"),
                "transferred_in": 0,
                "transferred_out": 0,
            },
        )
        summary[owner_id]["transferred_out"] = row["count"]
        if not summary[owner_id]["agent_name"]:
            summary[owner_id]["agent_name"] = row.get("from_agent_name")

    output = []
    for entry in summary.values():
        entry["net"] = entry["transferred_in"] - entry["transferred_out"]
        output.append(entry)
    output.sort(key=lambda e: -(e["transferred_in"] + e["transferred_out"]))
    return output


# ---------------------------------------------------------------------------
# Manual assignment + force-reassignment
# ---------------------------------------------------------------------------


def _hubspot_assign(hubspot_ticket_id: str, owner_id: int) -> dict:
    """Best-effort HubSpot owner update — non-fatal on failure."""
    from apps.integrations.hubspot.client import get_hubspot_client

    return get_hubspot_client().assign_ticket_owner(hubspot_ticket_id, owner_id)


def _ensure_agent_is_currently_eligible(agent: Agent) -> None:
    """Reject manual assignment to an absent or stale agent."""
    from django.conf import settings

    if not settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED:
        return
    from apps.support.eligibility_service import evaluate_persisted_agent

    decision = evaluate_persisted_agent(agent, timezone.now())
    if not decision.eligible:
        raise ValidationError(
            f"Agent is not eligible for assignment ({decision.reason.value}). "
            "Refresh availability from HubSpot before retrying."
        )


@router.post(
    "/queue/manual-assign/",
    response=AssignmentActionResponse,
    summary="Manually assign a pending ticket to a specific agent",
)
@require_manager_or_admin
def manual_assign(request, payload: ManualAssignRequest) -> dict:
    """Move a ticket from ``new_conversations`` directly to ``assigned_conversations``
    for the agent identified by ``agent_id`` regardless of the round-robin order.
    """
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_manual_assign")
    try:
        agent = Agent.objects.get(pk=payload.agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Agent with id={payload.agent_id} not found.") from err

    _ensure_agent_is_currently_eligible(agent)

    new_conv = NewConversation.objects.filter(hubspot_ticket_id=payload.hubspot_ticket_id).first()
    already_assigned = AssignedConversation.objects.filter(hubspot_ticket_id=payload.hubspot_ticket_id).first()

    if not new_conv and not already_assigned:
        raise NotFoundError(f"No pending or assigned conversation for ticket {payload.hubspot_ticket_id}.")

    if already_assigned:
        # Treat as a force-reassign for an already-assigned ticket.
        actor_email = getattr(getattr(request, "auth", None), "email", "admin")
        return _force_reassign_internal(
            payload.hubspot_ticket_id,
            agent,
            reason="manual_assign_existing",
            actor_email=actor_email,
        )

    actor_email = getattr(getattr(request, "auth", None), "email", "admin")
    from apps.support.durable_assignment_service import (
        execute_assignment_attempt,
        reserve_manual_assignment,
    )

    reservation = reserve_manual_assignment(
        ticket_id=payload.hubspot_ticket_id,
        agent_id=agent.pk,
        requested_by=actor_email,
    )
    if reservation.attempt is None:
        raise ValidationError(f"Manual assignment could not be reserved ({reservation.reason}).")
    outcome = execute_assignment_attempt(reservation.attempt.pk)
    if outcome != "assigned":
        raise ValidationError(f"HubSpot owner assignment was not confirmed ({outcome}).")

    logger.info(
        "manual_assign_success",
        ticket_id=payload.hubspot_ticket_id,
        agent_id=str(agent.id),
        actor=actor_email,
    )
    return {
        "success": True,
        "hubspot_ticket_id": payload.hubspot_ticket_id,
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "detail": "Ticket assigned manually.",
    }


def _force_reassign_internal(
    hubspot_ticket_id: str,
    target_agent: Agent,
    reason: str | None = None,
    actor_email: str | None = None,
) -> dict:
    """Force-reassign a ticket already present in assigned_conversations."""
    from apps.support.availability_runtime import require_routing_writer_authority

    require_routing_writer_authority("admin_force_reassign")
    _ensure_agent_is_currently_eligible(target_agent)
    assigned = AssignedConversation.objects.filter(hubspot_ticket_id=hubspot_ticket_id).first()
    if not assigned:
        raise NotFoundError(f"No assigned conversation for ticket {hubspot_ticket_id} — cannot force reassign.")
    if assigned.hubspot_owner_id == target_agent.hubspot_owner_id:
        return {
            "success": True,
            "hubspot_ticket_id": hubspot_ticket_id,
            "agent_id": str(target_agent.id),
            "agent_name": target_agent.name,
            "detail": "Target agent already owns this ticket — no-op.",
        }

    now = timezone.now()
    previous_agent = assigned.agent
    duration_with_previous: Decimal | None = None
    if assigned.assigned_at:
        duration_with_previous = Decimal(str(round((now - assigned.assigned_at).total_seconds(), 2)))

    _hubspot_assign(hubspot_ticket_id, target_agent.hubspot_owner_id)

    with transaction.atomic():
        ConversationReassignment.objects.create(
            hubspot_ticket_id=hubspot_ticket_id,
            from_agent=previous_agent,
            from_hubspot_owner_id=assigned.hubspot_owner_id,
            from_agent_name=assigned.agent_name,
            to_agent=target_agent,
            to_hubspot_owner_id=target_agent.hubspot_owner_id,
            to_agent_name=target_agent.name,
            reassigned_at=now,
            time_with_previous_agent_seconds=duration_with_previous,
            reassignment_source=reason or "admin_force_reassign",
        )
        assigned.agent = target_agent
        assigned.hubspot_owner_id = target_agent.hubspot_owner_id
        assigned.agent_name = target_agent.name
        assigned.assigned_at = now
        assigned.assignment_count = (assigned.assignment_count or 0) + 1
        assigned.save(
            update_fields=[
                "agent",
                "hubspot_owner_id",
                "agent_name",
                "assigned_at",
                "assignment_count",
                "updated_at",
            ]
        )
        AssignmentLog.objects.create(
            ticket_id=hubspot_ticket_id,
            agent=target_agent,
            agent_name=target_agent.name,
            hubspot_owner_id=target_agent.hubspot_owner_id,
            assignment_type="forced_reassign",
            assigned_by=actor_email,
            pipeline_id=assigned.pipeline_id,
        )
        if previous_agent:
            decrement_agent_chat_count(previous_agent)
        increment_agent_chat_count(target_agent)

    logger.info(
        "force_reassign_success",
        ticket_id=hubspot_ticket_id,
        from_agent_id=str(previous_agent.id) if previous_agent else None,
        to_agent_id=str(target_agent.id),
        actor=actor_email,
        reason=reason,
    )
    return {
        "success": True,
        "hubspot_ticket_id": hubspot_ticket_id,
        "agent_id": str(target_agent.id),
        "agent_name": target_agent.name,
        "detail": "Ticket reassigned.",
    }


@router.post(
    "/queue/force-reassign/",
    response=AssignmentActionResponse,
    summary="Forcefully reassign an assigned ticket to another agent",
)
@require_manager_or_admin
def force_reassign(request, payload: ForceReassignRequest) -> dict:
    """Move an already-assigned ticket to a different agent and audit the change.

    Decrements the previous agent's count, increments the new agent's count,
    writes a ``ConversationReassignment`` row, and pushes the change to HubSpot
    when reachable. The ``reason`` is recorded as the reassignment source.
    """
    try:
        target = Agent.objects.get(pk=payload.target_agent_id)
    except Agent.DoesNotExist as err:
        raise NotFoundError(f"Target agent with id={payload.target_agent_id} not found.") from err

    actor_email = getattr(getattr(request, "auth", None), "email", "admin")
    return _force_reassign_internal(
        payload.hubspot_ticket_id,
        target,
        reason=payload.reason,
        actor_email=actor_email,
    )
