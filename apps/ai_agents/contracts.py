"""Typed contracts for independent JUDAH AI capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field


class ConversationMessage(BaseModel):
    """A provider-neutral message inside a conversation context."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["INCOMING", "OUTGOING", "UNKNOWN"] = "UNKNOWN"
    text: str
    created_at: str | None = None
    actor_id: str | None = None
    message_id: str | None = None


class ScheduleResolution(BaseModel):
    """Provider-neutral snapshot of the effective Help Desk schedule."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["UNKNOWN", "OPEN", "CLOSED", "ABSENCE"] = "UNKNOWN"
    is_open_now: bool = False
    reason: str | None = None
    message: str | None = None
    source_rule_id: str | None = None
    source_rule_name: str | None = None
    priority: int | None = None

    @classmethod
    def from_runtime(cls, value: Self | Mapping[str, object]) -> Self:
        """Normalize the schedule resolver payload into this contract."""
        if isinstance(value, cls):
            return value
        source_rule_id = value.get("source_rule_id")
        return cls.model_validate(
            {
                "state": value.get("state", "UNKNOWN"),
                "is_open_now": value.get("is_open_now", False),
                "reason": value.get("reason"),
                "message": value.get("message"),
                "source_rule_id": str(source_rule_id) if source_rule_id else None,
                "source_rule_name": value.get("source_rule_name"),
                "priority": value.get("priority"),
            }
        )


class ConversationContext(BaseModel):
    """Provider-neutral context for an independent AI interaction."""

    model_config = ConfigDict(extra="forbid")

    channel: Literal["hubspot", "webchat_central", "api"]
    session_id: str
    ticket_id: str | None = None
    thread_id: str | None = None
    contact_id: str | None = None
    church_id: str | None = None
    pipeline_id: str | None = None
    pipeline_stage: str | None = None
    owner_id: str | None = None
    service_cycle_id: str | None = None
    service_cycle_idempotency_key: str | None = None
    attendance_sequence: int = Field(default=1, ge=1)
    is_reopened: bool = False
    reopen_count: int = Field(default=0, ge=0)
    reopened_from_state: str | None = None
    reopen_reason: str | None = None
    is_off_hours: bool = False
    schedule_resolution: ScheduleResolution = Field(default_factory=ScheduleResolution)
    can_send_reply: bool = True
    recent_messages: list[ConversationMessage] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)


class ActionIntent(BaseModel):
    """A structured action recommendation produced by an independent agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    idempotency_key: str | None = None


class SalomaoChatDraft(BaseModel):
    """Normalized draft produced by the standalone Salomao adapter."""

    model_config = ConfigDict(extra="forbid")

    response_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    resolved: bool
    requires_human_handoff: bool
    handoff_reason: str | None = None
    missing_data: list[str] = Field(default_factory=list)
    recommended_actions: list[ActionIntent] = Field(default_factory=list)
    customer_visible_protocol: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model_name: str | None = None


__all__ = [
    "ActionIntent",
    "ConversationContext",
    "ConversationMessage",
    "SalomaoChatDraft",
    "ScheduleResolution",
]
