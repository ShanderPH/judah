"""Pydantic v2 schemas for support endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ninja import Field, Schema


class QueueResponse(Schema):
    id: UUID
    name: str
    slug: str
    is_active: bool

    class Config:
        from_attributes = True


class TicketListResponse(Schema):
    id: UUID
    ticket_id: str
    customer_name: str | None = None
    ticket_church: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class TicketResponse(Schema):
    id: UUID
    ticket_id: str
    customer_name: str | None = None
    ticket_church: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    affected_device: str | None = None
    scope_of_impact: str | None = None
    affected_module: str | None = None
    affected_functionality: str | None = None
    created_at: datetime
    closed_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class CreateTicketRequest(Schema):
    ticket_id: str
    customer_name: str | None = None
    ticket_church: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    affected_device: str | None = None
    scope_of_impact: str | None = None
    affected_module: str | None = None
    affected_functionality: str | None = None
    created_at: datetime | None = None


class UpdateTicketRequest(Schema):
    status: str | None = None
    priority: str | None = None
    category: str | None = None
    affected_device: str | None = None
    scope_of_impact: str | None = None
    affected_module: str | None = None
    affected_functionality: str | None = None
    closed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Auto-assignment queue schemas
# ---------------------------------------------------------------------------


class AgentQueueStatusSchema(Schema):
    """Agent status as seen by the assignment queue."""

    id: str
    name: str
    hubspot_owner_id: int
    status: str
    current_chats: int
    max_chats: int
    last_assignment_at: datetime | None = None

    class Config:
        from_attributes = True


class QueueStatusResponse(Schema):
    """Current state of the assignment queue."""

    online_agents: int
    eligible_agents: int
    pending_queue_depth: int
    agents: list[AgentQueueStatusSchema]


class NewConversationResponse(Schema):
    """A ticket waiting in the assignment queue."""

    id: UUID
    hubspot_ticket_id: str
    pipeline_id: str
    contact_name: str | None = None
    contact_email: str | None = None
    priority: str | None = None
    subject: str | None = None
    entered_queue_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class AssignedConversationResponse(Schema):
    """A ticket that has been assigned by the auto-assignment system."""

    id: UUID
    hubspot_ticket_id: str
    agent_name: str
    hubspot_owner_id: int
    pipeline_id: str
    entered_queue_at: datetime | None = None
    assigned_at: datetime
    queue_wait_seconds: Decimal | None = None
    closed_at: datetime | None = None
    closed_by_agent_name: str | None = None
    total_handle_time_minutes: Decimal | None = None
    contact_name: str | None = None
    priority: str | None = None
    subject: str | None = None

    class Config:
        from_attributes = True


class QueueMetricsResponse(Schema):
    """Daily queue performance metrics."""

    id: UUID
    metric_date: str
    total_entered_queue: int
    total_assigned: int
    total_closed: int
    avg_queue_wait_seconds: Decimal | None = None
    min_queue_wait_seconds: Decimal | None = None
    max_queue_wait_seconds: Decimal | None = None
    p50_queue_wait_seconds: Decimal | None = None
    p95_queue_wait_seconds: Decimal | None = None
    avg_handle_time_minutes: Decimal | None = None
    assignments_by_agent: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Queue health / diagnostics schemas
# ---------------------------------------------------------------------------


class AgentDiagnosticSchema(Schema):
    """Full agent detail as returned by the health endpoint."""

    id: str
    name: str
    email: str
    hubspot_owner_id: int
    status: str
    current_chats: int
    max_chats: int
    eligible: bool
    at_capacity: bool
    auto_assign_enabled: bool | None = None
    last_assignment_at: datetime | None = None
    is_last_assigned: bool = False


class AbsentAgentSchema(Schema):
    """An agent currently excluded from the queue."""

    name: str
    hubspot_owner_id: int
    status: str
    open_chats: int


class PendingTicketSchema(Schema):
    """A ticket waiting in the assignment queue."""

    hubspot_ticket_id: str
    priority: str | None = None
    contact_name: str | None = None
    entered_queue_at: datetime
    wait_seconds: float


class LastAssignmentSchema(Schema):
    """A recent assignment log entry."""

    ticket_id: str
    agent_name: str
    hubspot_owner_id: int | None = None
    assignment_type: str
    queue_wait_seconds: float | None = None
    assigned_at: datetime


class QueueSummarySchema(Schema):
    """High-level counts for the queue health check."""

    total_agents: int
    online_agents: int
    away_agents: int
    eligible_agents: int
    pending_queue_depth: int
    system_ok: bool
    warnings: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class QueueHealthResponse(Schema):
    """Full diagnostic snapshot of the auto-assignment system."""

    timestamp: datetime
    summary: QueueSummarySchema
    absent_agents: list[AbsentAgentSchema]
    eligible_agents: list[AgentDiagnosticSchema]
    pending_tickets: list[PendingTicketSchema]
    last_assignments: list[LastAssignmentSchema]


class SyncNovoResponse(Schema):
    """Result of a NOVO-stage sync operation."""

    created: int
    skipped: int
    already_assigned: int = 0
    total_from_hubspot: int
    queued_for_assignment: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Business hours schemas
# ---------------------------------------------------------------------------


class BusinessHoursResponse(Schema):
    """Current business hours configuration."""

    name: str
    is_active: bool
    monday: str
    tuesday: str
    wednesday: str
    thursday: str
    friday: str
    saturday: str
    sunday: str
    timezone_name: str
    is_currently_business_hours: bool


class SpecialScheduleResponse(Schema):
    """A special schedule override."""

    id: UUID
    date: str
    schedule_type: str
    start_hour: int | None = None
    end_hour: int | None = None
    reason: str = ""

    class Config:
        from_attributes = True


class CreateSpecialScheduleRequest(Schema):
    """Request body for creating a special schedule."""

    date: str
    schedule_type: str = "closed"
    start_hour: int | None = None
    end_hour: int | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Agent administration schemas
# ---------------------------------------------------------------------------


class AgentResponse(Schema):
    """Public detail of a support agent."""

    id: UUID
    name: str
    agent_email: str
    hubspot_owner_id: int
    team: str | None = None
    manager_email: str | None = None
    status_enum: str
    current_simultaneous_chats: int
    max_simultaneous_chats: int
    auto_assign_enabled: bool
    is_active: bool | None = None
    timezone: str
    last_assignment_at: datetime | None = None
    total_assignments: int
    online_time_seconds_today: int
    away_time_seconds_today: int
    last_status_change_at: datetime | None = None

    class Config:
        from_attributes = True


class CreateAgentRequest(Schema):
    """Payload for creating a new agent."""

    name: str
    agent_email: str
    hubspot_owner_id: int
    team: str | None = None
    manager_email: str | None = None
    timezone: str = "America/Sao_Paulo"
    max_simultaneous_chats: int = 5
    auto_assign_enabled: bool = True


class UpdateAgentRequest(Schema):
    """Payload for partially updating an agent."""

    name: str | None = None
    team: str | None = None
    manager_email: str | None = None
    timezone: str | None = None
    max_simultaneous_chats: int | None = Field(default=None, ge=0, le=50)
    auto_assign_enabled: bool | None = None
    is_active: bool | None = None
    status_enum: str | None = None


# ---------------------------------------------------------------------------
# Metrics / time-log / reassignment read schemas
# ---------------------------------------------------------------------------


class AgentMetricsResponse(Schema):
    id: UUID
    agent_id: int
    period_start: str | None = None
    period_end: str | None = None
    average_online_time: float
    average_away_time: float
    average_daily_tickets: int
    average_response_time_min: float
    average_ticket_time_min: float
    tickets_transfer: int
    csat: int
    total_chats: int
    chats_closed: int
    first_response_time_avg_min: Decimal | None = None
    resolution_rate: Decimal | None = None
    customer_satisfaction_avg: Decimal | None = None
    last_time_updated: datetime

    class Config:
        from_attributes = True


class AgentDailyTimeLogResponse(Schema):
    id: UUID
    agent_id: UUID
    log_date: str
    online_time_seconds: int
    away_time_seconds: int
    status_transitions: int

    class Config:
        from_attributes = True


class ConversationReassignmentResponse(Schema):
    id: UUID
    hubspot_ticket_id: str
    from_agent_name: str | None = None
    from_hubspot_owner_id: int | None = None
    to_agent_name: str | None = None
    to_hubspot_owner_id: int | None = None
    reassigned_at: datetime
    time_with_previous_agent_seconds: Decimal | None = None
    reassignment_source: str

    class Config:
        from_attributes = True


class ReassignmentSummary(Schema):
    """Aggregated reassignment counts for an agent."""

    hubspot_owner_id: int
    agent_name: str | None = None
    transferred_in: int
    transferred_out: int
    net: int


class AgentMetricsSummary(Schema):
    """High-level aggregation over the period filter."""

    period_days: int
    total_agents_with_data: int
    total_chats: int
    total_chats_closed: int
    avg_handle_time_min: float
    avg_first_response_min: float
    avg_resolution_rate: float
    avg_csat: float


# ---------------------------------------------------------------------------
# Manual assignment schemas
# ---------------------------------------------------------------------------


class ManualAssignRequest(Schema):
    hubspot_ticket_id: str
    agent_id: UUID


class ForceReassignRequest(Schema):
    hubspot_ticket_id: str
    target_agent_id: UUID
    reason: str | None = None


class AssignmentActionResponse(Schema):
    success: bool
    hubspot_ticket_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    detail: str
