"""Pydantic v2 schemas for analytics endpoints."""

from typing import TYPE_CHECKING

from ninja import Schema

if TYPE_CHECKING:
    from datetime import date


class DailyReportResponse(Schema):
    """Daily report representation."""

    date: date
    total_tickets_opened: int
    total_tickets_resolved: int
    total_tickets_escalated: int
    avg_resolution_hours: float
    avg_first_response_hours: float
    sla_compliance_rate: float
    ai_handled_count: int
    ai_deflection_rate: float

    class Config:
        from_attributes = True


class MetricDataPoint(Schema):
    """Single metric data point."""

    date: date
    metric_type: str
    value: float

    class Config:
        from_attributes = True


class AgentPerformanceResponse(Schema):
    """Agent performance summary."""

    agent_id: int
    date: date
    tickets_handled: int
    tickets_resolved: int
    avg_resolution_hours: float
    sla_breached_count: int

    class Config:
        from_attributes = True
