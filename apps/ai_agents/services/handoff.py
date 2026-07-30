"""Human handoff package builder for AI-to-support transfers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from apps.ai_agents.contracts import ConversationContext, HandoffPackage, TriageDecision
from apps.ai_agents.models import ConversationInstance

_MAX_MESSAGE_SNIPPET = 240
_MAX_CONVERSATION_SUMMARY = 900
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
    "frustrado",
    "frustrante",
    "nao consegui",
    "nao funciona",
    "ninguem responde",
    "pessimo",
    "problema",
    "sem resposta",
)
_URGENCY_MARKERS = (
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


def _plain_text(value: str) -> str:
    """Remove chat formatting while preserving the text an N1 needs to read."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    text = re.sub(r"[*_`~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _customer_texts(conversation_context: ConversationContext | None) -> list[str]:
    if conversation_context is None:
        return []
    return [
        message.text.strip()
        for message in conversation_context.recent_messages
        if message.direction == "INCOMING" and message.text.strip()
    ]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _explicit_human_request(text: str) -> bool:
    return _contains_any(text, _EXPLICIT_HUMAN_MARKERS)


def _customer_requested_topics(normalized_text: str) -> set[str]:
    """Extract stable support topics without inventing facts from an AI response."""
    topics: set[str] = set()
    if "evento" in normalized_text and any(marker in normalized_text for marker in ("ingresso", "inscricao", "ticket")):
        topics.add("event_ticket")
    if any(marker in normalized_text for marker in ("estorno", "devolucao", "reembolso")):
        topics.add("refund")
    if any(marker in normalized_text for marker in ("confirmacao", "comunicacao", "enviar o ingresso")):
        topics.add("confirmation")
    if any(marker in normalized_text for marker in ("camiseta", "campo da inscricao", "dados do participante")):
        topics.add("registration_fields")
    if any(marker in normalized_text for marker in ("pix", "cartao", "boleto", "forma de pagamento")):
        topics.add("payment_methods")
    if any(marker in normalized_text for marker in ("validade", "prazo", "data final", "encerrar as vendas")):
        topics.add("sales_period")
    if "cupom" in normalized_text and any(marker in normalized_text for marker in ("criar", "configurar", "desconto")):
        topics.add("discount_coupon")
    if any(marker in normalized_text for marker in ("membro", "pessoa")) and any(
        marker in normalized_text for marker in ("excluir", "inativar", "desativar")
    ):
        topics.add("member_deactivation")
    if any(marker in normalized_text for marker in ("protocolo", "caso que reportei", "status do chamado")):
        topics.add("case_status")
    if any(marker in normalized_text for marker in ("planos", "valores", "comercial")):
        topics.add("commercial")
    return topics


def _event_ticket_summary(normalized_text: str, topics: set[str]) -> str:
    paid = any(marker in normalized_text for marker in ("ingresso pago", "ticket pago", "pagamento"))
    ticket_type = "ingresso pago" if paid else "ingresso"
    event_name_match = re.search(r"\bevento (?:de|do|da) ([a-z0-9-]{3,40})", normalized_text)
    event_name = event_name_match.group(1) if event_name_match else ""
    generic_event_names = {"igreja", "minha", "nosso", "nossa", "um", "uma"}
    event_reference = (
        f"o evento de {event_name.capitalize()}"
        if event_name and event_name not in generic_event_names
        else "um evento"
    )
    sentences = [f"O cliente está configurando um {ticket_type} para {event_reference}."]

    quantity_match = re.search(r"\b(\d{1,5})\s+(?:ingressos?|vagas?)\b", normalized_text)
    if quantity_match:
        sentences.append(f"Precisa limitar a disponibilidade a {quantity_match.group(1)} ingressos.")

    payment_methods = [
        label
        for marker, label in (("pix", "PIX"), ("cartao", "cartão"), ("boleto", "boleto"))
        if marker in normalized_text
    ]
    if payment_methods:
        sentences.append(f"Quer aceitar {' e '.join(payment_methods)}.")
    if "sales_period" in topics:
        sentences.append("Também precisa definir o período de vendas ou a validade do ingresso.")
    if "registration_fields" in topics:
        sentences.append("Precisa configurar os dados da inscrição, inclusive as informações adicionais solicitadas.")
    if "confirmation" in topics:
        sentences.append("Quer confirmar o envio automático da confirmação e do ingresso após o pagamento.")
    if "refund" in topics:
        sentences.append("Também pediu orientação sobre estorno e o registro do cancelamento.")
    return " ".join(sentences)


def _general_topic_summary(topics: set[str]) -> str:
    topic_labels = {
        "discount_coupon": "criar ou configurar um cupom de desconto",
        "member_deactivation": "inativar ou remover o cadastro de um membro",
        "case_status": "consultar o andamento de um caso ou protocolo",
        "commercial": "conhecer planos, valores ou falar com o Comercial",
        "refund": "realizar o estorno de um pagamento",
    }
    ordered_topics = [
        topic_labels[key]
        for key in ("discount_coupon", "member_deactivation", "case_status", "commercial", "refund")
        if key in topics
    ]
    if not ordered_topics:
        return ""
    if len(ordered_topics) == 1:
        topic_text = ordered_topics[0]
    else:
        topic_text = f"{', '.join(ordered_topics[:-1])} e {ordered_topics[-1]}"
    return f"O cliente precisa de orientação para {topic_text}."


def assess_customer_tone(
    conversation_context: ConversationContext | None,
    triage_decision: TriageDecision | None,
) -> tuple[str, str]:
    """Classify the customer's observable tone without overstating certainty."""
    normalized_text = _normalized(" ".join(_customer_texts(conversation_context)))
    sentiment = triage_decision.sentimento if triage_decision is not None else "neutro"
    is_cordial = _contains_any(normalized_text, _POSITIVE_MARKERS)

    if _contains_any(normalized_text, _AGGRESSIVE_MARKERS):
        return "Irritado/agressivo", "Há linguagem agressiva ou cobrança direta no histórico recente."
    if _contains_any(normalized_text, _FRUSTRATION_MARKERS):
        if is_cordial:
            return (
                "Frustrado, porém cordial",
                "O cliente relata dificuldade para concluir, mas mantém uma comunicação respeitosa.",
            )
        return "Frustrado", "O cliente relata repetição, demora ou falta de solução."
    if _contains_any(normalized_text, _URGENCY_MARKERS):
        return "Preocupado/urgente", "O cliente sinaliza necessidade de resolução rápida."
    if _contains_any(normalized_text, _CONFUSION_MARKERS):
        return "Confuso", "O cliente demonstra dúvida ou dificuldade para entender o procedimento."
    if sentiment == "negativo":
        return "Frustrado", "A triagem identificou sentimento negativo, sem linguagem agressiva explícita."
    if sentiment == "positivo" or is_cordial:
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
    """Build a compact synthesis grounded only in customer-authored messages."""
    customer_messages = _customer_texts(conversation_context)
    normalized_text = _normalized(" ".join(customer_messages))
    topics = _customer_requested_topics(normalized_text)
    parts: list[str] = []

    if "event_ticket" in topics:
        parts.append(_event_ticket_summary(normalized_text, topics))
    elif customer_messages:
        topic_summary = _general_topic_summary(topics)
        if topic_summary:
            parts.append(topic_summary)
        substantive_messages = [
            _plain_text(message)
            for message in customer_messages
            if _plain_text(message) and not _explicit_human_request(_normalized(message))
        ]
        if substantive_messages and not topic_summary:
            compact_requests = "; ".join(_shorten(message, 220) for message in substantive_messages[-3:])
            parts.append(f"O cliente solicitou orientação sobre: {compact_requests}.")

    if _contains_any(normalized_text, _FRUSTRATION_MARKERS):
        parts.append("Após as orientações, informou que ainda não conseguiu concluir o procedimento.")
    if _explicit_human_request(normalized_text):
        parts.append("O cliente pediu continuidade com um atendente humano.")

    if not parts:
        parts.append(f"Motivo do encaminhamento: {_humanize_handoff_reason(reason)}")

    # ``ai_summary`` is intentionally not copied: it is usually the last long
    # Salomão answer and caused internal notes to contain raw Markdown and
    # duplicated instructions instead of a support-oriented synthesis.
    _ = ai_summary
    return _shorten(" ".join(parts), _MAX_CONVERSATION_SUMMARY)


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
    explicit_human_request = _explicit_human_request(normalized_messages) or (
        "explicit" in normalized_reason and "human" in normalized_reason
    )
    topics = _customer_requested_topics(normalized_messages)

    opening = (
        "Acolha a frustração do cliente e confirme que assumiu o caso. "
        if customer_tone in {"Irritado/agressivo", "Frustrado", "Frustrado, porém cordial"}
        else "Assuma a conversa e confirme brevemente o entendimento do caso. "
    )

    if missing_data:
        pending = ", ".join(item.replace("_", " ") for item in missing_data[:5])
        return f"{opening}Confirme os dados pendentes ({pending}) e prossiga sem pedir que o cliente repita o restante."
    if "event_ticket" in topics:
        checks = ["o ponto exato em que a configuração do ingresso ficou bloqueada"]
        if "payment_methods" in topics or "sales_period" in topics:
            checks.append("formas de pagamento e período de vendas")
        if "registration_fields" in topics or "confirmation" in topics:
            checks.append("campos da inscrição e comunicação automática")
        if "refund" in topics:
            checks.append("elegibilidade do estorno e registro do cancelamento")
        return (
            f"{opening}Valide {', '.join(checks[:-1])}"
            f"{' e ' if len(checks) > 1 else ''}{checks[-1]}. "
            "Use os dados já registrados e confirme o resultado com o cliente antes de encerrar."
        )
    topic_actions = {
        "case_status": (
            "Consulte o protocolo ou os casos da igreja com o identificador já informado, confirme título, "
            "status e prioridade e explique objetivamente o andamento."
        ),
        "refund": (
            "Identifique a transação e valide sua elegibilidade para estorno antes de orientar ou executar "
            "o procedimento."
        ),
        "discount_coupon": (
            "Confirme em qual etapa da configuração do cupom surgiu a dúvida e valide regras, período e aplicação "
            "do desconto."
        ),
        "member_deactivation": (
            "Confirme qual cadastro deve ser inativado e valide o impacto da ação antes de orientar a alteração."
        ),
        "commercial": (
            "Confirme o interesse da igreja e garanta que o contato comercial tenha os dados necessários para "
            "dar continuidade."
        ),
    }
    selected_actions = [
        topic_actions[topic]
        for topic in ("case_status", "refund", "discount_coupon", "member_deactivation", "commercial")
        if topic in topics
    ]
    if selected_actions:
        return (
            f"{opening}{' '.join(selected_actions)} "
            "Continue com o histórico disponível, sem pedir que o cliente repita informações."
        )
    if explicit_human_request:
        return (
            f"{opening}Continue a partir do histórico já registrado e valide somente a pendência ainda não resolvida, "
            "sem pedir que o cliente repita o que já informou."
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
        f"**Tom do cliente:** {package.get('customer_tone') or 'Indeterminado'}",
    ]
    tone_context = str(package.get("customer_tone_context") or "").strip()
    if tone_context:
        lines.append(f"**Sinais observados:** {tone_context}")
    lines.extend(
        [
            "",
            f"**Resumo da conversa:** {package.get('conversation_summary') or 'Sem histórico textual suficiente.'}",
        ]
    )
    church_plan = package.get("church_plan")
    if isinstance(church_plan, dict):
        plan = _plain_text(str(church_plan.get("plan") or "")).strip() or "Não informado"
        is_active = church_plan.get("is_active")
        is_blocked = church_plan.get("is_blocked")
        active_label = "Sim" if is_active is True else "Não" if is_active is False else "Não informado"
        blocked_label = "Sim" if is_blocked is True else "Não" if is_blocked is False else "Não informado"
        lines.extend(
            [
                "",
                f"**Plano da igreja:** `{plan}` — **is_active:** {active_label}; **is_blocked:** {blocked_label}",
            ]
        )
    else:
        church_plan_message = _plain_text(str(package.get("church_plan_lookup_message") or "")).strip()
        lines.extend(
            [
                "",
                f"**Plano da igreja:** {church_plan_message or 'Não foi possível consultar.'}",
            ]
        )
    obtained_modules = package.get("obtained_modules") or []
    if obtained_modules:
        lines.extend(["", "**Módulos obtidos:**"])
        for module in obtained_modules:
            if not isinstance(module, dict):
                continue
            alias = re.sub(r"\s+", " ", str(module.get("alias") or "").replace("`", "")).strip()
            if not alias:
                continue
            details = []
            name = _plain_text(str(module.get("name") or "")).strip()
            price = _plain_text(str(module.get("price") or "")).strip()
            plan_limit = _plain_text(str(module.get("plan_limit") or "")).strip()
            if name:
                details.append(f"name: {name}")
            if price:
                details.append(f"price: {price}")
            if plan_limit:
                details.append(f"limite {plan_limit}")
            suffix = f" — {', '.join(details)}" if details else ""
            lines.append(f"- `{alias}`{suffix}")
    else:
        module_lookup_message = _plain_text(str(package.get("module_lookup_message") or "")).strip()
        lines.extend(
            [
                "",
                f"**Módulos obtidos:** {module_lookup_message or 'Nenhum módulo ativo foi retornado.'}",
            ]
        )
    lines.extend(
        [
            "",
            f"**Próximo passo recomendado:** {package.get('recommended_next_step') or 'Revisar o histórico e assumir o atendimento.'}",
        ]
    )
    priority = str(package.get("priority") or "").strip()
    if priority:
        priority_label = {
            "CRITICA": "Crítica",
            "ALTA": "Alta",
            "MEDIA": "Média",
            "BAIXA": "Baixa",
        }.get(priority.upper(), priority)
        lines.extend(["", f"**Prioridade da triagem:** {priority_label}"])
    missing_data = [str(item).replace("_", " ") for item in package.get("missing_data") or [] if str(item).strip()]
    if missing_data:
        lines.extend(["", f"**Dados ainda necessários:** {', '.join(missing_data[:5])}"])
    return "\n".join(lines)


def build_handoff_package(
    *,
    instance: ConversationInstance,
    reason: str,
    conversation_context: ConversationContext | None = None,
    triage_decision: TriageDecision | None = None,
    ai_summary: str = "",
    missing_data: list[str] | None = None,
    feature_subscription_lookup: dict[str, Any] | None = None,
    church_plan_lookup: dict[str, Any] | None = None,
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
    module_lookup = feature_subscription_lookup or {
        "church_id": conversation_context.church_id if conversation_context is not None else None,
        "module_lookup_status": "not_requested",
        "module_lookup_message": "Consulta de módulos não executada.",
        "obtained_modules": [],
    }
    plan_lookup = church_plan_lookup or {
        "church_plan_lookup_status": "not_requested",
        "church_plan_lookup_message": "Consulta do plano da igreja não executada.",
        "church_plan": None,
    }
    package = HandoffPackage(
        conversation_instance_id=str(instance.pk),
        state=instance.state,
        hubspot_thread_id=instance.hubspot_thread_id,
        hubspot_ticket_id=instance.hubspot_ticket_id,
        hubspot_contact_id=instance.hubspot_contact_id,
        church_id=module_lookup.get("church_id"),
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
        module_lookup_status=str(module_lookup.get("module_lookup_status") or "not_requested"),
        module_lookup_message=str(module_lookup.get("module_lookup_message") or ""),
        obtained_modules=list(module_lookup.get("obtained_modules") or []),
        church_plan_lookup_status=str(plan_lookup.get("church_plan_lookup_status") or "not_requested"),
        church_plan_lookup_message=str(plan_lookup.get("church_plan_lookup_message") or ""),
        church_plan=plan_lookup.get("church_plan"),
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
