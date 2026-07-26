"""Human handoff package builder for AI-to-support transfers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from apps.ai_agents.contracts import ConversationContext, HandoffPackage, TriageDecision
from apps.ai_agents.models import ConversationInstance

_MAX_MESSAGE_SNIPPET = 240
_AGGRESSIVE_MARKERS = (
    "absurdo",
    "caralho",
    "incompetente",
    "lixo",
    "merda",
    "patetico",
    "porra",
    "ridiculo",
    "vergonha",
)
_FRUSTRATION_MARKERS = (
    "cansei",
    "continua sem",
    "de novo",
    "demora",
    "esperando",
    "nao funciona",
    "ninguem responde",
    "pessimo",
    "problema",
    "sem resposta",
)
_URGENCY_MARKERS = (
    "agora",
    "critico",
    "imediatamente",
    "o quanto antes",
    "urgente",
)
_CONFUSION_MARKERS = (
    "como faco",
    "nao entendi",
    "nao sei",
    "pode explicar",
    "tenho duvida",
)
_POSITIVE_MARKERS = (
    "agradeco",
    "obrigada",
    "obrigado",
    "perfeito",
    "por favor",
)
_EXPLICIT_HUMAN_MARKERS = (
    "atendente",
    "falar com alguem",
    "falar com humano",
    "pessoa da equipe",
    "suporte humano",
)


def _normalized(value: str) -> str:
    """Normalize customer text for conservative tone and intent matching."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _shorten(value: str, limit: int = _MAX_MESSAGE_SNIPPET) -> str:
    """Return a compact single-line excerpt without cutting a word when possible."""
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    shortened = compact[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{shortened}…"


def _customer_texts(conversation_context: ConversationContext | None) -> list[str]:
    if conversation_context is None:
        return []
    return [
        message.text.strip()
        for message in conversation_context.recent_messages
        if message.direction == "INCOMING" and message.text.strip()
    ]


def _agent_texts(conversation_context: ConversationContext | None) -> list[str]:
    if conversation_context is None:
        return []
    return [
        message.text.strip()
        for message in conversation_context.recent_messages
        if message.direction == "OUTGOING" and message.text.strip()
    ]


def assess_customer_tone(
    conversation_context: ConversationContext | None,
    triage_decision: TriageDecision | None,
) -> tuple[str, str]:
    """Classify the customer's observable tone without overstating certainty."""
    normalized_text = _normalized(" ".join(_customer_texts(conversation_context)))
    sentiment = triage_decision.sentimento if triage_decision is not None else "neutro"

    if any(marker in normalized_text for marker in _AGGRESSIVE_MARKERS):
        return "Irritado", "Há linguagem agressiva ou cobrança direta no histórico recente."
    if any(marker in normalized_text for marker in _FRUSTRATION_MARKERS):
        return "Frustrado", "O cliente relata repetição, demora ou falta de solução."
    if any(marker in normalized_text for marker in _URGENCY_MARKERS):
        return "Preocupado/urgente", "O cliente sinaliza necessidade de resolução rápida."
    if any(marker in normalized_text for marker in _CONFUSION_MARKERS):
        return "Confuso", "O cliente demonstra dúvida ou dificuldade para entender o procedimento."
    if sentiment == "negativo":
        return "Frustrado", "A triagem identificou sentimento negativo, sem linguagem agressiva explícita."
    if sentiment == "positivo" or any(marker in normalized_text for marker in _POSITIVE_MARKERS):
        return "Calmo/positivo", "O cliente mantém linguagem cordial ou demonstra satisfação."
    if normalized_text:
        return "Calmo/neutro", "Não há sinais claros de irritação, urgência ou frustração."
    return "Indeterminado", "Não há texto suficiente do cliente para inferir o tom com segurança."


def _humanize_handoff_reason(reason: str) -> str:
    normalized_reason = _normalized(reason)
    if "explicit" in normalized_reason and "human" in normalized_reason:
        return "O cliente solicitou atendimento humano."
    if "low confidence" in normalized_reason:
        return "A IA não teve confiança suficiente para concluir o atendimento com segurança."
    if "retry budget exhausted" in normalized_reason:
        return "Ocorreram falhas técnicas repetidas no fluxo automatizado."
    if "not authorize an automated reply" in normalized_reason:
        return "O contexto do canal não autorizou uma resposta automática segura."
    return _shorten(reason, 400) or "O atendimento exige continuidade por uma pessoa da equipe."


def summarize_conversation(
    *,
    conversation_context: ConversationContext | None,
    reason: str,
    ai_summary: str,
) -> str:
    """Build an extractive, bounded summary grounded only in the observed conversation."""
    customer_messages = _customer_texts(conversation_context)
    agent_messages = _agent_texts(conversation_context)
    parts: list[str] = []

    if customer_messages:
        customer_excerpt = " | ".join(_shorten(message) for message in customer_messages[-3:])
        parts.append(f"O cliente informou: “{customer_excerpt}”.")
    if agent_messages:
        parts.append(f"O Salomão já respondeu: “{_shorten(agent_messages[-1])}”.")

    normalized_ai_summary = _normalized(ai_summary)
    if ai_summary.strip() and not any(
        marker in normalized_ai_summary
        for marker in ("encaminhar", "falar com humano", "pessoa do nosso time", "transferir")
    ):
        parts.append(f"Contexto produzido pela IA: {_shorten(ai_summary, 320)}")

    parts.append(f"Motivo do encaminhamento: {_humanize_handoff_reason(reason)}")
    return " ".join(parts)


def recommend_next_step(
    *,
    conversation_context: ConversationContext | None,
    triage_decision: TriageDecision | None,
    reason: str,
    customer_tone: str,
    missing_data: list[str],
) -> str:
    """Recommend one actionable N1 continuation grounded in route and missing context."""
    normalized_messages = _normalized(" ".join(_customer_texts(conversation_context)))
    normalized_reason = _normalized(reason)
    explicit_human_request = any(marker in normalized_messages for marker in _EXPLICIT_HUMAN_MARKERS) or (
        "explicit" in normalized_reason and "human" in normalized_reason
    )

    opening = (
        "Acolha a frustração do cliente e confirme que assumiu o caso. "
        if customer_tone in {"Irritado", "Frustrado"}
        else "Assuma a conversa e confirme brevemente o entendimento do caso. "
    )

    if missing_data:
        pending = ", ".join(item.replace("_", " ") for item in missing_data[:5])
        return f"{opening}Confirme os dados pendentes ({pending}) e prossiga sem pedir que o cliente repita o restante."
    if explicit_human_request:
        return (
            f"{opening}Continue a partir do histórico já registrado e pergunte apenas qual resultado o cliente "
            "espera obter, caso isso ainda não esteja claro."
        )

    route = triage_decision.rota if triage_decision is not None else ""
    route_actions = {
        "BOLETO": "Valide a cobrança, o período e a identificação necessária antes de orientar ou corrigir a emissão.",
        "EVENTOS": "Confirme o evento, o participante/ingresso e reproduza o ponto exato onde o fluxo falhou.",
        "DUVIDAS_PLATAFORMA": "Revise a orientação já enviada e complemente somente o passo que permaneceu sem resposta.",
        "MEIOS_DE_PAGAMENTO": "Confirme a transação, o meio de pagamento e o status no painel antes de orientar a igreja.",
        "FINANCEIRO": "Valide a transação e a elegibilidade da operação no painel antes de indicar o procedimento.",
        "SUPORTE_TECNICO_N1": "Reproduza o cenário com os dados já informados e solicite evidência adicional somente se indispensável.",
        "CUSTOMER_SUCCESS": "Entenda o objetivo da igreja e indique a ação ou acompanhamento mais adequado.",
        "ESCALAR_IMEDIATAMENTE": "Priorize a análise, valide o impacto e envolva o responsável adequado sem atrasar o primeiro retorno.",
    }
    action = route_actions.get(
        route,
        "Revise o histórico, confirme o diagnóstico e dê continuidade sem fazer o cliente repetir informações.",
    )
    return f"{opening}{action}"


def format_handoff_observation(package: dict[str, Any]) -> str:
    """Render the handoff package as a concise HubSpot internal observation."""
    lines = [
        "## Resumo automático do Salomão para o N1",
        "",
        f"**Tom percebido:** {package.get('customer_tone') or 'Indeterminado'}",
    ]
    tone_context = str(package.get("customer_tone_context") or "").strip()
    if tone_context:
        lines.append(f"**Sinais observados:** {tone_context}")
    lines.extend(
        [
            "",
            f"**Resumo da conversa:** {package.get('conversation_summary') or 'Sem histórico textual suficiente.'}",
            "",
            f"**Próximo passo recomendado:** {package.get('recommended_next_step') or 'Revisar o histórico e assumir o atendimento.'}",
        ]
    )
    priority = str(package.get("priority") or "").strip()
    if priority:
        lines.extend(["", f"**Prioridade da triagem:** {priority}"])
    missing_data = [str(item).replace("_", " ") for item in package.get("missing_data") or [] if str(item).strip()]
    if missing_data:
        lines.extend(["", f"**Dados ainda necessários:** {', '.join(missing_data[:5])}"])
    lines.extend(["", "_Observação interna gerada no momento do encaminhamento para Novo._"])
    return "\n".join(lines)


def build_handoff_package(
    *,
    instance: ConversationInstance,
    reason: str,
    conversation_context: ConversationContext | None = None,
    triage_decision: TriageDecision | None = None,
    ai_summary: str = "",
    missing_data: list[str] | None = None,
) -> dict[str, Any]:
    """Build the minimum context a human agent needs after AI escalation."""
    recent_messages = []
    if conversation_context is not None:
        recent_messages = [
            {
                "direction": message.direction,
                "text": message.text,
                "created_at": message.created_at,
                "actor_id": message.actor_id,
                "message_id": message.message_id,
            }
            for message in conversation_context.recent_messages[-10:]
        ]

    triage_payload = triage_decision.model_dump(mode="json") if triage_decision is not None else None
    effective_missing_data = missing_data or (triage_payload.get("dados_faltantes", []) if triage_payload else [])
    customer_tone, customer_tone_context = assess_customer_tone(conversation_context, triage_decision)
    conversation_summary = summarize_conversation(
        conversation_context=conversation_context,
        reason=reason,
        ai_summary=ai_summary,
    )
    recommended_next_step = recommend_next_step(
        conversation_context=conversation_context,
        triage_decision=triage_decision,
        reason=reason,
        customer_tone=customer_tone,
        missing_data=effective_missing_data,
    )
    package = HandoffPackage(
        conversation_instance_id=str(instance.pk),
        state=instance.state,
        hubspot_thread_id=instance.hubspot_thread_id,
        hubspot_ticket_id=instance.hubspot_ticket_id,
        hubspot_contact_id=instance.hubspot_contact_id,
        source_message_id=instance.last_message_id or instance.last_event_id,
        channel=instance.channel,
        assigned_agent_id=instance.assigned_agent_id,
        reason=reason,
        priority=triage_payload.get("prioridade") if triage_payload else None,
        tags=triage_payload.get("tags", []) if triage_payload else [],
        missing_data=effective_missing_data,
        triage=triage_payload,
        ai_summary=ai_summary,
        customer_tone=customer_tone,
        customer_tone_context=customer_tone_context,
        conversation_summary=conversation_summary,
        recommended_next_step=recommended_next_step,
        recent_messages=recent_messages,
        recommended_queue="support_n1",
    )
    return package.model_dump(mode="json")


__all__ = [
    "assess_customer_tone",
    "build_handoff_package",
    "format_handoff_observation",
    "recommend_next_step",
    "summarize_conversation",
]
