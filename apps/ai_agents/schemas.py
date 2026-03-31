"""Pydantic v2 schemas for ai_agents endpoints."""

from datetime import datetime

from ninja import Schema


class ChatRequest(Schema):
    """Payload for sending a message to an AI agent."""

    message: str
    session_id: str | None = None
    agent_type: str = "salomao"
    channel: str = "api"
    user_identifier: str = ""
    church_external_id: str = ""
    hubspot_contact_id: str = ""


class ChatResponse(Schema):
    """AI agent response to a chat message."""

    session_id: str
    message: str
    agent_type: str
    sources: list[dict] = []
    tokens_used: int = 0
    latency_ms: int = 0


class TriageRequest(Schema):
    """Payload for triaging an incoming message."""

    message: str
    channel: str = "whatsapp"
    user_identifier: str = ""
    church_external_id: str = ""


class TriageResult(Schema):
    """Result of Heimdall triage classification."""

    intent: str
    confidence: float
    suggested_queue: str | None = None
    suggested_priority: str = "medium"
    requires_human: bool = False
    reasoning: str = ""


class SessionResponse(Schema):
    """AI agent session representation."""

    session_id: str
    agent_type: str
    channel: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
