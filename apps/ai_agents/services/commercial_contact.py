"""Deterministic commercial-contact policy for customer conversations."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from apps.ai_agents.services.conversation_turn import current_incoming_turn_text

COMMERCIAL_CONTACT_MESSAGE = (
    "Caso tenham interesse em conhecer melhor os nossos planos, valores e tudo o que a InChurch oferece, "
    "é só preencher este formulário comercial:\n\n"
    "[https://form.typeform.com/to/S7EC8j4N](https://form.typeform.com/to/S7EC8j4N)\n\n"
    "Assim que o formulário for enviado, nossa equipe comercial entrará em contato com a igreja para "
    "apresentar as opções e esclarecer todas as dúvidas."
)

_DIRECT_COMMERCIAL_PATTERNS = (
    re.compile(
        r"\b(?:falar|conversar|contato|atendimento|encaminh\w*|transfer\w*|pass\w*)\b.{0,60}"
        r"\b(?:comercial|vendas|consultor)\b"
    ),
    re.compile(
        r"\b(?:comercial|vendas|consultor)\b.{0,60}"
        r"\b(?:falar|conversar|contato|atendimento|encaminh\w*|transfer\w*|pass\w*)\b"
    ),
    re.compile(
        r"\b(?:quero|gostaria|preciso|temos?|tenho|estou)\b.{0,80}"
        r"\b(?:contratar|adquirir|assinar|conhecer)\b.{0,80}"
        r"\b(?:inchurch|plano|planos|valor|valores|servico|servicos|plataforma)\b"
    ),
    re.compile(
        r"\b(?:quero|gostaria|tenho interesse|temos interesse)\b.{0,80}"
        r"\b(?:planos?|valores?|orcamento|proposta|demonstracao)\b"
    ),
    re.compile(r"\b(?:quanto custa|qual o preco|qual o valor)\b.{0,50}\b(?:a )?inchurch\b"),
    re.compile(r"\b(?:planos e valores|planos da inchurch|valores da inchurch|precos da inchurch)\b"),
    re.compile(r"\b(?:tenho|temos) interesse\b.{0,50}\b(?:na|pela) inchurch\b"),
    re.compile(r"\b(?:quero|gostaria|preciso)\b.{0,40}\b(?:contratar|adquirir|assinar)\b"),
    re.compile(r"\b(?:quais|conhecer|ver)\b.{0,40}\b(?:planos?|valores?)\b"),
)
_COMMERCIAL_CONTEXT_TERMS = (
    "equipe comercial",
    "time comercial",
    "falar com o comercial",
    "planos e valores",
    "formulario comercial",
    "contratar a inchurch",
)
_AFFIRMATIVE_PATTERN = re.compile(
    r"^(?:sim|quero|gostaria|pode ser|por favor|tenho interesse|temos interesse|claro|isso)(?:[!. ]*)$"
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char)).split()
    )


def _recent_outgoing_text(context: dict[str, Any]) -> str:
    outgoing = [
        _normalize(str(message.get("text") or ""))
        for message in context.get("conversation_history") or []
        if str(message.get("direction") or "").upper() == "OUTGOING" and message.get("text")
    ]
    return " ".join(outgoing[-3:])


def has_commercial_contact_intent(context: dict[str, Any]) -> bool:
    """Return whether the current turn explicitly requests commercial contact."""
    current_turn = _normalize(current_incoming_turn_text(context))
    if not current_turn:
        return False
    if any(pattern.search(current_turn) for pattern in _DIRECT_COMMERCIAL_PATTERNS):
        return True
    if _AFFIRMATIVE_PATTERN.fullmatch(current_turn):
        recent_outgoing = _recent_outgoing_text(context)
        return any(term in recent_outgoing for term in _COMMERCIAL_CONTEXT_TERMS)
    return False


def handle_commercial_contact_from_hubspot_context(context: dict[str, Any]) -> str | None:
    """Return the approved commercial form message for an eligible turn."""
    return COMMERCIAL_CONTACT_MESSAGE if has_commercial_contact_intent(context) else None


__all__ = [
    "COMMERCIAL_CONTACT_MESSAGE",
    "handle_commercial_contact_from_hubspot_context",
    "has_commercial_contact_intent",
]
