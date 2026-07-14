"""Typed contracts used for handoffs between JUDAH AI agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TriageDecision(BaseModel):
    """Central triage contract shared by Heimdall, the Supervisor, and adapter agents."""

    model_config = ConfigDict(extra="forbid")

    rota: Literal[
        "BOLETO",
        "EVENTOS",
        "DUVIDAS_PLATAFORMA",
        "MEIOS_DE_PAGAMENTO",
        "FINANCEIRO",
        "SUPORTE_TECNICO_N1",
        "CUSTOMER_SUCCESS",
        "ESCALAR_IMEDIATAMENTE",
        "ATENDIMENTO_IA",
    ]
    prioridade: Literal["CRITICA", "ALTA", "MEDIA", "BAIXA"]
    tags: list[str] = Field(default_factory=list)
    dados_faltantes: list[str] = Field(default_factory=list)
    sentimento: Literal["positivo", "neutro", "negativo"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    policy_version: str = "heimdall-v1"


class ConversationMessage(BaseModel):
    """A provider-neutral message inside a conversation context."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["INCOMING", "OUTGOING", "UNKNOWN"] = "UNKNOWN"
    text: str
    created_at: str | None = None
    actor_id: str | None = None
    message_id: str | None = None


class ConversationContext(BaseModel):
    """Provider-neutral context passed into agent handoffs."""

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
    is_off_hours: bool = False
    can_send_reply: bool = True
    recent_messages: list[ConversationMessage] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)


class ActionIntent(BaseModel):
    """A structured action recommendation produced by an agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    idempotency_key: str | None = None


class HubSpotAction(BaseModel):
    """A HubSpot write action allowed only after SupervisorDecision."""

    model_config = ConfigDict(extra="forbid")

    action_type: Literal[
        "send_thread_reply",
        "update_ticket_stage",
        "assign_ticket_to_human_queue",
        "add_internal_note",
        "mark_ai_resolution_attempt",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class SalomaoChatDraft(BaseModel):
    """Normalized draft produced by the Salomao v1 adapter agent."""

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


class SupervisorDecision(BaseModel):
    """Internal structured decision before converting to SalomaoResponse."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["candidate_resolved", "waiting_customer", "escalate_human", "failed"]
    final_response: str
    hubspot_action: HubSpotAction | None = None
    trace_summary: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class HandoffPackage(BaseModel):
    """Structured context transferred from the AI workflow to a human queue."""

    model_config = ConfigDict(extra="forbid")

    conversation_instance_id: str
    state: str
    hubspot_thread_id: str | None = None
    hubspot_ticket_id: str | None = None
    hubspot_contact_id: str | None = None
    channel: str = ""
    assigned_agent_id: str | None = None
    reason: str
    priority: str | None = None
    tags: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    triage: dict[str, Any] | None = None
    ai_summary: str = ""
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    recommended_queue: str = "support_n1"


__all__ = [
    "ActionIntent",
    "ConversationContext",
    "ConversationMessage",
    "HandoffPackage",
    "HubSpotAction",
    "SalomaoChatDraft",
    "SupervisorDecision",
    "TriageDecision",
]
