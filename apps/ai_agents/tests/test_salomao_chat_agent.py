"""Tests for the Salomao v1 adapter agent/tool."""

from __future__ import annotations

from django.test import override_settings

from apps.ai_agents.agents.salomao_chat import SalomaoChatTool, salomao_v1_result_to_draft
from apps.ai_agents.contracts import ConversationContext, ConversationMessage
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, SalomaoV1TokenUsage
from common.exceptions import ExternalServiceError


class FakeSalomaoClient:
    async def chat(self, *, message: str, session_id: str) -> SalomaoV1ChatResult:
        assert "Mensagem atual:\nComo fazer um cupom?" in message
        assert session_id == "hubspot-thread-123"
        return SalomaoV1ChatResult(
            response="Para criar um cupom, acesse Eventos e configure o desconto.",
            session_id=session_id,
            transfer_requested=False,
            model_used="gpt-4o-mini",
            tokens=SalomaoV1TokenUsage(prompt=10, completion=20, total=30),
        )


class FailingSalomaoClient:
    async def chat(self, *, message: str, session_id: str) -> SalomaoV1ChatResult:
        raise ExternalServiceError("salomao_v1", "provider unavailable")


def _conversation_context() -> ConversationContext:
    return ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-123",
        ticket_id="456",
        thread_id="123",
        recent_messages=[
            ConversationMessage(direction="INCOMING", text="Como fazer um cupom?"),
        ],
    )


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
async def test_salomao_chat_tool_returns_structured_draft() -> None:
    tool = SalomaoChatTool(
        session_id="fallback-session",
        client_factory=FakeSalomaoClient,
    )

    draft = await tool.create_chat_draft_async(
        message="Como fazer um cupom?",
        conversation_context=_conversation_context(),
    )

    assert draft.response_text.startswith("Para criar um cupom")
    assert draft.resolved is True
    assert draft.requires_human_handoff is False
    assert draft.recommended_actions[0].name == "send_thread_reply"
    assert draft.customer_visible_protocol == "#456"
    assert draft.prompt_tokens == 10
    assert draft.completion_tokens == 20
    assert draft.total_tokens == 30
    assert draft.model_name == "gpt-4o-mini"


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
async def test_salomao_chat_tool_returns_handoff_draft_on_client_error() -> None:
    tool = SalomaoChatTool(
        session_id="fallback-session",
        client_factory=FailingSalomaoClient,
    )

    draft = await tool.create_chat_draft_async(
        message="Como fazer um cupom?",
        conversation_context=_conversation_context(),
    )

    assert draft.resolved is False
    assert draft.requires_human_handoff is True
    assert draft.recommended_actions[0].name == "assign_ticket_to_human_queue"
    assert "ExternalServiceError" in (draft.handoff_reason or "")


def test_salomao_v1_empty_response_becomes_handoff_draft() -> None:
    draft = salomao_v1_result_to_draft(
        SalomaoV1ChatResult(
            response=" ",
            session_id="hubspot-thread-123",
        ),
        conversation_context=_conversation_context(),
    )

    assert draft.resolved is False
    assert draft.requires_human_handoff is True
    assert draft.confidence == 0.0
