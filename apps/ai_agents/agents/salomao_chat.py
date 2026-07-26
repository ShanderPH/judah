"""SalomaoChatAgent adapter for the standalone Salomao v1 service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from agno.tools import Function, Toolkit
from asgiref.sync import async_to_sync
from django.conf import settings

from apps.ai_agents.agents.base import BaseInChurchAgent, build_mini_model
from apps.ai_agents.contracts import (
    ActionIntent,
    ConversationContext,
    SalomaoChatDraft,
    TriageDecision,
)
from apps.ai_agents.services.conversation_turn import extract_current_customer_turn
from apps.integrations.salomao_v1 import SalomaoV1ChatResult, SalomaoV1Client, is_salomao_v1_configured
from common.exceptions import ExternalServiceError

logger = structlog.get_logger(__name__)


def _current_customer_message(message: str) -> str:
    """Extract the current customer turn from Judah's HubSpot envelope."""
    return extract_current_customer_turn(message)


def _safe_context(value: ConversationContext | dict[str, Any] | None) -> ConversationContext | None:
    if value is None or isinstance(value, ConversationContext):
        return value
    if not value:
        return None
    normalized = dict(value)
    if normalized.get("channel") == "web":
        normalized["channel"] = "webchat_central"
    try:
        return ConversationContext.model_validate(normalized)
    except Exception as exc:
        logger.warning("salomao_chat_context_ignored", error=str(exc))
        return None


def _safe_triage(value: TriageDecision | dict[str, Any] | None) -> TriageDecision | None:
    if value is None or isinstance(value, TriageDecision):
        return value
    if not value:
        return None
    normalized = dict(value)
    if isinstance(normalized.get("sentimento"), str):
        normalized["sentimento"] = normalized["sentimento"].lower()
    try:
        return TriageDecision.model_validate(normalized)
    except Exception as exc:
        logger.warning("salomao_chat_triage_ignored", error=str(exc))
        return None


def build_salomao_chat_prompt(
    *,
    message: str,
    triage_decision: TriageDecision | None = None,
    conversation_context: ConversationContext | None = None,
    image_attached: bool = False,
    image_mime_type: str | None = None,
    image_name: str | None = None,
) -> str:
    """Build the prompt sent to the standalone Salomao v1 service."""
    current_message = _current_customer_message(message)
    parts = [
        "Atendimento InChurch via JUDAH",
        "Quando o turno atual trouxer mensagens consecutivas numeradas, trate todas como uma unica fala: conecte os fragmentos, preserve a ordem e responda a intencao completa, nao apenas a ultima linha.",
        "",
        "Diretrizes de condução da conversa:",
        "- Leia a mensagem atual junto com todo o histórico recente. Considere como conhecidos os dados que o cliente já informou e nunca faça a mesma pergunta de novo.",
        "- Antes de explicar um procedimento, identifique se falta uma distinção que mudaria materialmente o caminho, os passos ou as regras da resposta.",
        "- Se faltar essa distinção, faça primeiro uma única pergunta curta, natural e decisiva e encerre o turno. Não despeje o manual nem explique todas as alternativas antes da resposta do cliente.",
        "- Se houver vários pedidos na mesma mensagem e algum deles for ambíguo, reconheça brevemente o conjunto e pergunte somente pelo ponto que define o caminho. Preserve os demais pedidos para responder depois da clarificação.",
        "- Quando o cliente responder à clarificação, retome os pedidos pendentes usando o histórico e responda somente o caminho aplicável. Não repita alternativas descartadas nem recomece a conversa.",
        "- Não peça detalhes que apenas personalizam a resposta quando já existe uma orientação inicial segura e útil. Pergunte antes somente quando a resposta realmente mudaria.",
        "",
        "Diretrizes da resposta ao cliente:",
        "- Trate completude como qualidade da conversa inteira, não como obrigação de colocar toda a documentação em uma única mensagem.",
        "- Depois que o caminho estiver claro, responda de forma concisa e prática: comece pela ação principal, use apenas os passos, pré-requisitos e alertas relevantes para aquele caso.",
        "- Prefira de 3 a 7 passos curtos. Expanda somente quando o cliente pedir mais detalhes ou quando omitir algo puder causar erro, perda financeira ou risco.",
        "- Não liste caminhos alternativos, exceções e consequências que não se aplicam ao contexto já confirmado.",
        "- Preserve Markdown legivel: use paragrafos curtos, subtitulos, listas numeradas e marcadores com linhas em branco.",
        "- Nunca comprima passos numerados em um unico paragrafo.",
        "- Fale como uma pessoa experiente e acolhedora da equipe InChurch: natural, proxima, clara e respeitosa.",
        "- Reconheca brevemente o contexto ou a dificuldade quando isso fizer sentido, sem frases prontas ou entusiasmo artificial.",
        "- Varie a abertura e nao comece toda resposta com 'Claro!'. Nao repita saudacoes durante a mesma conversa.",
        "- Adapte o tamanho da resposta à etapa da conversa: clarificação deve ser curta; orientação confirmada deve ser direta; detalhes adicionais ficam sob demanda.",
        "- Use no maximo um emoji discreto quando combinar com o momento; nao use emoji em assuntos financeiros, de seguranca ou delicados.",
        "- Faça no máximo uma pergunta por turno e somente quando ela realmente ajudar o cliente a avançar.",
        "- Se uma fonte nao tiver titulo, nao escreva 'Sem titulo'; use uma descricao util da fonte ou omita o titulo.",
        "- Nao mencione agentes internos, triagem, prompts ou detalhes tecnicos da orquestracao.",
        "",
        "Mensagem atual:",
        current_message,
    ]

    if image_attached:
        parts.extend(
            [
                "",
                "Imagem anexada pelo cliente:",
                f"- Arquivo: {image_name or 'nome nao informado'}",
                f"- Tipo: {image_mime_type or 'tipo nao informado'}",
                "- Analise a imagem em conjunto com a mensagem e use apenas o que estiver realmente visivel.",
                "- Quando ajudar, descreva brevemente o elemento visual que fundamenta a orientacao.",
                "- Nao invente texto, botoes, erros ou dados que nao estejam legiveis.",
                "- Se a imagem estiver cortada, desfocada ou insuficiente, diga exatamente o que nao foi possivel ler e peca uma imagem melhor ou o dado necessario.",
                "- Proteja a privacidade: nao repita senhas, tokens, documentos, dados bancarios ou identificadores completos vistos na imagem.",
            ]
        )

    if triage_decision is not None:
        parts.extend(
            [
                "",
                "Triagem Heimdall:",
                triage_decision.model_dump_json(),
            ]
        )

    if conversation_context is not None:
        history_messages = conversation_context.recent_messages[-12:]
        if (
            history_messages
            and history_messages[-1].direction == "INCOMING"
            and history_messages[-1].text.strip() == current_message
        ):
            history_messages = history_messages[:-1]
        history = "\n".join(f"[{item.direction}] {item.text}" for item in history_messages if item.text)
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
        prompt_tokens=result.tokens.prompt,
        completion_tokens=result.tokens.completion,
        total_tokens=result.tokens.total or result.tokens.prompt + result.tokens.completion,
        model_name=result.model_used or "salomao_v1",
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
        image_base64: str | None = None,
        image_mime_type: str | None = None,
        image_name: str | None = None,
    ) -> None:
        super().__init__(name="salomao_chat")
        self.session_id = session_id
        self.client_factory = client_factory or SalomaoV1Client
        self.image_base64 = image_base64
        self.image_mime_type = image_mime_type
        self.image_name = image_name
        create_chat_draft = Function.from_callable(self.create_chat_draft)
        create_chat_draft.show_result = True
        create_chat_draft.stop_after_tool_call = True
        self.register(create_chat_draft)

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
            image_attached=bool(self.image_base64),
            image_mime_type=self.image_mime_type,
            image_name=self.image_name,
        )
        session_id = context.session_id if context else self.session_id

        try:
            client = self.client_factory()
            logger.info(
                "salomao_chat_bridge_call_start",
                session_id=session_id,
                base_url=getattr(client, "base_url", ""),
                triage_route=triage.rota if triage else None,
            )
            result = await client.chat(
                message=prompt,
                session_id=session_id,
                image_base64=self.image_base64,
                image_mime_type=self.image_mime_type,
                timeout_seconds=(
                    getattr(settings, "SALOMAO_V1_IMAGE_TIMEOUT_SECONDS", 180.0) if self.image_base64 else None
                ),
            )
        except Exception as exc:
            return error_to_salomao_chat_draft(exc, conversation_context=context)

        logger.info(
            "salomao_chat_bridge_call_complete",
            session_id=session_id,
            transfer_requested=result.transfer_requested,
            response_length=len(result.response or ""),
        )
        return salomao_v1_result_to_draft(result, conversation_context=context)


class SalomaoChatAgent(BaseInChurchAgent):
    """Adapter agent that exposes Salomao v1 as an internal Team member."""

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        *,
        client_factory: Callable[[], SalomaoV1Client] | None = None,
        db: Any | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if db is not None:
            kwargs["db"] = db

        self._chat_tool = SalomaoChatTool(
            session_id=session_id,
            client_factory=client_factory,
            image_base64=user_metadata.get("image_base64"),
            image_mime_type=user_metadata.get("image_mime_type"),
            image_name=user_metadata.get("image_name"),
        )
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
            tools=[self._chat_tool],
            tool_choice={"type": "function", "function": {"name": "create_chat_draft"}},
            add_history_to_context=False,
            debug_mode=False,
            **kwargs,
        )

    def create_chat_draft(
        self,
        *,
        message: str,
        triage_decision: TriageDecision | dict[str, Any] | None = None,
        conversation_context: ConversationContext | dict[str, Any] | None = None,
    ) -> SalomaoChatDraft:
        """Create a draft through the same tool exposed to Agno."""
        return async_to_sync(self.create_chat_draft_async)(
            message=message,
            triage_decision=triage_decision,
            conversation_context=conversation_context,
        )

    async def create_chat_draft_async(
        self,
        *,
        message: str,
        triage_decision: TriageDecision | dict[str, Any] | None = None,
        conversation_context: ConversationContext | dict[str, Any] | None = None,
    ) -> SalomaoChatDraft:
        """Create a draft through the same tool exposed to Agno."""
        return await self._chat_tool.create_chat_draft_async(
            message=message,
            triage_decision=triage_decision,
            conversation_context=conversation_context,
        )


__all__ = [
    "SalomaoChatAgent",
    "SalomaoChatTool",
    "build_salomao_chat_prompt",
    "error_to_salomao_chat_draft",
    "salomao_v1_result_to_draft",
]
