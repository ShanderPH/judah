"""Pydantic v2 schemas for support endpoints."""

from typing import TYPE_CHECKING

from ninja import Schema

if TYPE_CHECKING:
    from datetime import datetime


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
