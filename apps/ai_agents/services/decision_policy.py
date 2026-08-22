"""Deterministic response-quality signals for independent AI replies."""

from __future__ import annotations

import re
import unicodedata

_CUSTOMER_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:me|nos)\s+(?:avise|confirme|conte|de|diga|dizer|envie|explique|informe|mande|mostre|"
        r"responda|retorne)\b"
    ),
    re.compile(r"\b(?:de|da|mande|envie|compartilhe)\s+(?:um\s+)?retorno\b"),
    re.compile(r"\b(?:retorne|responda)\s+(?:aqui\s+)?com\b"),
    re.compile(r"\bconfirme\s+se\b"),
    re.compile(r"\b(?:aguardo|aguardamos|ficarei aguardando)\s+(?:o\s+)?(?:seu\s+)?retorno\b"),
    re.compile(
        r"\b(?:anexe|compartilhe|envie|mande)\s+(?:aqui\s+)?(?:um|uma)\s+"
        r"(?:audio|video|arquivo|documento|anexo|gravacao|captura|foto|imagem|print|screenshot)\b"
    ),
    re.compile(r"\b(?:pode|podem)\s+(?:mandar|enviar|anexar|compartilhar)\b"),
    re.compile(
        r"\b(?:n[oa]|nesse|nessa)\s+(?:audio|video|arquivo|documento|anexo|gravacao)\b"
        r"[^.!?]{0,80}\b(?:mencione|informe|inclua|mostre|explique)\b"
    ),
    re.compile(r"\b(?:mensagem|codigo)\s+d[eo]\s+erro\s+(?:que\s+)?(?:aparece|apareceu|recebeu)\b"),
    re.compile(
        r"\b(?:preciso|precisamos|vou precisar)\s+(?:de|que voce envie)\s+(?:mais\s+)?"
        r"(?:dados|detalhes|informacoes)\b"
    ),
    re.compile(r"\b(?:para|pra)\s+(?:eu|nos)\s+(?:continuar|analisar|investigar|te orientar|verificar)\b"),
    re.compile(r"\b(?:fico|ficamos)\s+(?:aqui\s+)?no aguardo\b"),
    re.compile(r"\b(?:depois|em seguida)\s+(?:me|nos)\s+(?:avise|conte|diga|envie|mande|informe)\b"),
)

_POSITIVE_RESOLUTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:acesse|abra|clique|selecione|localize|configure|preencha|salve|ative|desative|"
        r"altere|cadastre|crie|entre|va)\b"
    ),
    re.compile(
        r"\b(?:ajuste|configuracao|orientacao|processo|procedimento|solicitacao)\s+"
        r"(?:concluido|concluida|finalizado|finalizada|resolvido|resolvida)\b"
    ),
    re.compile(r"\b(?:agora|assim)\s+(?:esta|fica|ficara)\s+(?:pronto|pronta|configurado|configurada)\b"),
    re.compile(r"\bresposta\s+final\b"),
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"\s+", " ", normalized).split())


def _customer_facing_prose(text: str) -> str:
    """Return prose that can require an answer, excluding Markdown headings."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"[-_*]{3,}", line):
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def customer_input_signals(text: str) -> list[str]:
    """Identify evidence that a response still expects customer information.

    A conclusively resolved turn cannot contain a customer-facing question or
    ask for evidence such as an error message or screenshot. Markdown headings
    such as ``## O que fazer?`` are excluded because they label instructions
    rather than request a new customer turn.
    """
    prose = _customer_facing_prose(text)
    normalized = _normalize(prose)
    signals: list[str] = []
    if "?" in prose:
        signals.append("open_question")
    if any(pattern.search(normalized) for pattern in _CUSTOMER_INPUT_PATTERNS):
        signals.append("additional_customer_data_requested")
    return signals


def resolution_evidence_signals(text: str) -> list[str]:
    """Identify positive evidence that the response actually answers the case."""
    prose = _customer_facing_prose(text)
    normalized = _normalize(prose)
    signals: list[str] = []
    if re.search(r"(?m)^\s*\d+[.)]\s+\S", prose):
        signals.append("procedural_steps")
    if any(pattern.search(normalized) for pattern in _POSITIVE_RESOLUTION_PATTERNS):
        signals.append("actionable_or_explicit_resolution")
    return signals


__all__ = [
    "customer_input_signals",
    "resolution_evidence_signals",
]
