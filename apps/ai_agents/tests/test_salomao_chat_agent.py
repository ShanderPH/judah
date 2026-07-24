"""Tests for the Salomao v1 adapter agent/tool."""

from __future__ import annotations

from django.test import override_settings

from apps.ai_agents.agents.salomao_chat import (
    SalomaoChatTool,
    build_salomao_chat_prompt,
    salomao_v1_result_to_draft,
)
from apps.ai_agents.contracts import ConversationContext, ConversationMessage
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, SalomaoV1TokenUsage
from common.exceptions import ExternalServiceError


class FakeSalomaoClient:
    async def chat(
        self,
        *,
        message: str,
        session_id: str,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SalomaoV1ChatResult:
        assert "Mensagem atual:\nComo fazer um cupom?" in message
        assert message.count("Como fazer um cupom?") == 1
        assert "Atendimento HubSpot\nTicket:" not in message
        assert "500 a 900 caracteres" not in message
        assert "no maximo 5 passos" not in message
        assert "faça primeiro uma única pergunta curta" in message
        assert "Não despeje o manual" in message
        assert "completude como qualidade da conversa inteira" in message
        assert "responda somente o caminho aplicável" in message
        assert "nunca faça a mesma pergunta de novo" in message
        assert "Preserve Markdown legivel" in message
        assert "experiente e acolhedora" in message
        assert "Nao repita saudacoes" in message
        assert session_id == "hubspot-thread-123"
        return SalomaoV1ChatResult(
            response=(
                "## Como criar um cupom\n\n"
                "1. Acesse **Eventos**.\n"
                "2. Abra **Ingressos**.\n\n"
                "## Atenção\n\n- Revise a validade antes de salvar."
            ),
            session_id=session_id,
            transfer_requested=False,
            model_used="gpt-5.5",
            tokens=SalomaoV1TokenUsage(prompt=10, completion=20, total=30),
        )


class FailingSalomaoClient:
    async def chat(self, *, message: str, session_id: str, **_kwargs) -> SalomaoV1ChatResult:
        raise ExternalServiceError("salomao_v1", "provider unavailable")


class ImageSalomaoClient:
    async def chat(
        self,
        *,
        message: str,
        session_id: str,
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SalomaoV1ChatResult:
        assert "base64" not in message
        assert image_base64 == "aW1hZ2U="
        assert image_mime_type == "image/png"
        assert timeout_seconds == 180.0
        assert "Imagem anexada pelo cliente:" in message
        assert "Arquivo: erro-financeiro.png" in message
        assert "Tipo: image/png" in message
        assert "Nao invente texto, botoes, erros ou dados" in message
        assert "nao repita senhas, tokens" in message
        return SalomaoV1ChatResult(response="A imagem mostra a tela de eventos.", session_id=session_id)


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


def test_salomao_chat_prompt_extracts_grouped_customer_turn() -> None:
    prompt = build_salomao_chat_prompt(
        message=(
            "Atendimento HubSpot\nTicket: 456\nHistorico recente:\n"
            "[OUTGOING] Como posso ajudar?\n\n"
            "Turno atual do cliente (mensagens consecutivas, em ordem):\n"
            "1. Tenho interesse\n2. nos planos e valores"
        )
    )

    assert "Mensagem atual:\n1. Tenho interesse\n2. nos planos e valores" in prompt
    assert "responda a intencao completa" in prompt
    assert "Atendimento HubSpot\nTicket: 456" not in prompt


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
async def test_salomao_chat_tool_returns_structured_draft() -> None:
    tool = SalomaoChatTool(
        session_id="fallback-session",
        client_factory=FakeSalomaoClient,
    )

    draft = await tool.create_chat_draft_async(
        message=(
            "Atendimento HubSpot\nTicket: 456\nHistorico recente:\n[INCOMING] Como fazer um cupom?\n\n"
            "Mensagem atual do cliente:\nComo fazer um cupom?"
        ),
        conversation_context=_conversation_context(),
    )

    assert draft.response_text.startswith("## Como criar um cupom\n\n1.")
    assert "\n\n## Atenção\n\n- " in draft.response_text
    assert draft.resolved is True
    assert draft.requires_human_handoff is False
    assert draft.recommended_actions[0].name == "send_thread_reply"
    assert draft.customer_visible_protocol == "#456"
    assert draft.prompt_tokens == 10
    assert draft.completion_tokens == 20
    assert draft.total_tokens == 30
    assert draft.model_name == "gpt-5.5"


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


@override_settings(SALOMAO_V1_BASE_URL="http://salomao.local")
async def test_salomao_chat_tool_forwards_image_outside_prompt() -> None:
    tool = SalomaoChatTool(
        session_id="fallback-session",
        client_factory=ImageSalomaoClient,
        image_base64="aW1hZ2U=",
        image_mime_type="image/png",
        image_name="erro-financeiro.png",
    )

    draft = await tool.create_chat_draft_async(
        message="Analise esta imagem.",
        conversation_context=_conversation_context(),
    )

    assert draft.response_text == "A imagem mostra a tela de eventos."


def test_prompt_uses_answered_clarification_and_preserves_pending_request() -> None:
    context = ConversationContext(
        channel="hubspot",
        session_id="hubspot-thread-clarification",
        ticket_id="789",
        thread_id="clarification",
        recent_messages=[
            ConversationMessage(
                direction="INCOMING",
                text="Como criar cupom e fazer estorno?",
            ),
            ConversationMessage(
                direction="OUTGOING",
                text="O estorno é de evento ou de doação?",
            ),
            ConversationMessage(
                direction="INCOMING",
                text="É de inscrição de evento.",
            ),
        ],
    )

    prompt = build_salomao_chat_prompt(
        message="É de inscrição de evento.",
        conversation_context=context,
    )

    assert "[INCOMING] Como criar cupom e fazer estorno?" in prompt
    assert "[OUTGOING] O estorno é de evento ou de doação?" in prompt
    assert prompt.count("É de inscrição de evento.") == 1
    assert "Preserve os demais pedidos para responder depois da clarificação" in prompt


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
