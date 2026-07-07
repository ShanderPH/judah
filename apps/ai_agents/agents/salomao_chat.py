"""SalomaoChatAgent adapter for the standalone Salomao v1 service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from agno.tools import Toolkit
from asgiref.sync import async_to_sync

from apps.ai_agents.agents.base import BaseInChurchAgent, build_mini_model
from apps.ai_agents.contracts import (
    ActionIntent,
    ConversationContext,
    SalomaoChatDraft,
    TriageDecision,
)
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, SalomaoV1Client, is_salomao_v1_configured
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)


def _safe_context(value: ConversationContext | dict[str, Any] | None) -> ConversationContext | None:
    if value is None or isinstance(value, ConversationContext):
        return value
    return ConversationContext.model_validate(value)


def _safe_triage(value: TriageDecision | dict[str, Any] | None) -> TriageDecision | None:
    if value is None or isinstance(value, TriageDecision):
        return value
    return TriageDecision.model_validate(value)


def build_salomao_chat_prompt(
    *,
    message: str,
    triage_decision: TriageDecision | None = None,
    conversation_context: ConversationContext | None = None,
) -> str:
    """Build the prompt sent to the standalone Salomao v1 service."""
    parts = ["Atendimento InChurch via JUDAH", "", "Mensagem atual:", message]

    if triage_decision is not None:
        parts.extend(
            [
                "",
                "Triagem Heimdall:",
                triage_decision.model_dump_json(),
            ]
        )

    if conversation_context is not None:
        history = "\n".join(
            f"[{item.direction}] {item.text}" for item in conversation_context.recent_messages[-12:] if item.text
        )
        parts.extend(
            [
                "",
                "Contexto da conversa:",
                conversation_context.model_dump_json(exclude={"recent_messages"}),
            ]
        )
        if history:
            parts.extend(["", "Historico recente:", history])

    return "\n".join(parts)


def salomao_v1_result_to_draft(
    result: SalomaoV1ChatResult,
    *,
    conversation_context: ConversationContext | None = None,
) -> SalomaoChatDraft:
    """Normalize a Salomao v1 response into the internal draft contract."""
    response_text = result.response.strip()
    if not response_text:
        return SalomaoChatDraft(
            response_text="Nao consegui gerar uma resposta segura agora. Vou encaminhar para um atendente humano.",
            confidence=0.0,
            resolved=False,
            requires_human_handoff=True,
            handoff_reason="Salomao v1 returned an empty response.",
            missing_data=[],
            recommended_actions=[
                ActionIntent(
                    name="assign_ticket_to_human_queue",
                    reason="Empty response from Salomao v1.",
                    idempotency_key=_idempotency_key(conversation_context),
                )
            ],
            customer_visible_protocol=_protocol(conversation_context),
        )

    return SalomaoChatDraft(
        response_text=response_text,
        confidence=0.72 if result.transfer_requested else 0.86,
        resolved=not result.transfer_requested,
        requires_human_handoff=result.transfer_requested,
        handoff_reason="Salomao v1 requested transfer." if result.transfer_requested else None,
        missing_data=[],
        recommended_actions=_recommended_actions(result, conversation_context),
        customer_visible_protocol=_protocol(conversation_context),
    )


def error_to_salomao_chat_draft(
    error: Exception,
    *,
    conversation_context: ConversationContext | None = None,
) -> SalomaoChatDraft:
    """Return a safe draft for adapter failures without leaking provider details."""
    error_type = type(error).__name__
    logger.error("salomao_chat_adapter_failed", error_type=error_type, error=str(error))
    return SalomaoChatDraft(
        response_text="O atendimento com IA esta indisponivel no momento. Vou encaminhar para um atendente humano.",
        confidence=0.0,
        resolved=False,
        requires_human_handoff=True,
        handoff_reason=f"SalomaoChatAgent adapter failure: {error_type}",
        missing_data=[],
        recommended_actions=[
            ActionIntent(
                name="assign_ticket_to_human_queue",
                reason=f"Adapter failure: {error_type}",
                idempotency_key=_idempotency_key(conversation_context),
            )
        ],
        customer_visible_protocol=_protocol(conversation_context),
    )


def _protocol(context: ConversationContext | None) -> str | None:
    if context and context.ticket_id:
        return f"#{context.ticket_id}"
    return None


def _idempotency_key(context: ConversationContext | None) -> str | None:
    if context is None:
        return None
    if context.thread_id:
        return f"hubspot-thread:{context.thread_id}:salomao-chat"
    if context.ticket_id:
        return f"hubspot-ticket:{context.ticket_id}:salomao-chat"
    return f"session:{context.session_id}:salomao-chat"


def _recommended_actions(
    result: SalomaoV1ChatResult,
    context: ConversationContext | None,
) -> list[ActionIntent]:
    if result.transfer_requested:
        return [
            ActionIntent(
                name="assign_ticket_to_human_queue",
                reason="Salomao v1 requested transfer.",
                idempotency_key=_idempotency_key(context),
            )
        ]
    if context and context.thread_id:
        return [
            ActionIntent(
                name="send_thread_reply",
                reason="Reply to the active HubSpot conversation thread.",
                idempotency_key=_idempotency_key(context),
            )
        ]
    return []


class SalomaoChatTool(Toolkit):
    """Agno toolkit that exposes Salomao v1 as a typed chat draft tool."""

    def __init__(
        self,
        *,
        session_id: str,
        client_factory: Callable[[], SalomaoV1Client] | None = None,
    ) -> None:
        super().__init__(name="salomao_chat")
        self.session_id = session_id
        self.client_factory = client_factory or SalomaoV1Client
        self.register(self.create_chat_draft)

    def create_chat_draft(
        self,
        message: str,
        triage_decision: dict[str, Any] | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a SalomaoChatDraft as a JSON-serializable dict."""
        draft = async_to_sync(self.create_chat_draft_async)(
            message=message,
            triage_decision=triage_decision,
            conversation_context=conversation_context,
        )
        return draft.model_dump(mode="json")

    async def create_chat_draft_async(
        self,
        *,
        message: str,
        triage_decision: TriageDecision | dict[str, Any] | None = None,
        conversation_context: ConversationContext | dict[str, Any] | None = None,
    ) -> SalomaoChatDraft:
        """Call Salomao v1 and normalize its response to SalomaoChatDraft."""
        context = _safe_context(conversation_context)
        triage = _safe_triage(triage_decision)

        if not is_salomao_v1_configured():
            return error_to_salomao_chat_draft(
                ExternalServiceError("salomao_v1", "SALOMAO_V1_BASE_URL is not configured."),
                conversation_context=context,
            )

        prompt = build_salomao_chat_prompt(
            message=message,
            triage_decision=triage,
            conversation_context=context,
        )
        session_id = context.session_id if context else self.session_id

        try:
            result = await self.client_factory().chat(message=prompt, session_id=session_id)
        except Exception as exc:
            return error_to_salomao_chat_draft(exc, conversation_context=context)

        return salomao_v1_result_to_draft(result, conversation_context=context)


class SalomaoChatAgent(BaseInChurchAgent):
    """Adapter agent that exposes Salomao v1 as an internal Team member."""

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        *,
        client_factory: Callable[[], SalomaoV1Client] | None = None,
    ) -> None:
        super().__init__(
            session_id=session_id,
            user_metadata=user_metadata,
            name="SalomaoChat",
            model=build_mini_model(),
            instructions=[
                "Voce e o SalomaoChatAgent, adapter interno do Salomao v1.",
                "Sempre use a tool `create_chat_draft` para transformar a mensagem, a triagem e o contexto em um SalomaoChatDraft.",
                "Nunca exponha erros de provider, tokens, chaves ou stack traces ao usuario.",
                "Retorne ao Supervisor somente o draft estruturado e uma breve explicacao operacional.",
            ],
            tools=[SalomaoChatTool(session_id=session_id, client_factory=client_factory)],
            add_history_to_context=False,
            debug_mode=False,
        )


__all__ = [
    "SalomaoChatAgent",
    "SalomaoChatTool",
    "build_salomao_chat_prompt",
    "error_to_salomao_chat_draft",
    "salomao_v1_result_to_draft",
]
