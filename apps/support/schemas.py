"""Pydantic v2 schemas for support endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ninja import Field, Schema


class QueueResponse(Schema):
    id: int
    name: str
    slug: str
    is_active: bool

    class Config:
        from_attributes = True


class TicketListResponse(Schema):
    id: int
    subject: str
    status: str
    priority: str
    channel: str
    customer_email: str
    hubspot_ticket_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TicketResponse(Schema):
    id: int
    hubspot_ticket_id: str | None
    subject: str
    description: str
    status: str
    priority: str
    channel: str
    customer_email: str
    customer_name: str
    church_external_id: str
    sla_breached: bool
    first_response_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateTicketRequest(Schema):
    subject: str
    description: str = ""
    priority: str = "medium"
    channel: str = "email"
    customer_email: str = ""
    customer_name: str = ""
    church_external_id: str = ""
    queue_id: int | None = None


class UpdateTicketRequest(Schema):
    status: str | None = None
    priority: str | None = None
    assigned_to_id: int | None = None
    queue_id: int | None = None


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
    total_from_hubspot: int
    queued_for_assignment: bool
    error: str | None = None
