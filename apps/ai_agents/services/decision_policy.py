"""Deterministic safety policies for Supervisor decisions."""

from __future__ import annotations

import re
import unicodedata

from apps.ai_agents.contracts import SupervisorDecision

_CUSTOMER_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:me|nos)\s+(?:conte|diga|envie|explique|informe|mande|mostre)\b"),
    re.compile(
        r"\b(?:anexe|compartilhe|envie|mande)\s+(?:aqui\s+)?(?:um|uma)\s+"
        r"(?:captura|foto|imagem|print|screenshot)\b"
    ),
    re.compile(r"\b(?:mensagem|codigo)\s+d[eo]\s+erro\s+(?:que\s+)?(?:aparece|apareceu|recebeu)\b"),
    re.compile(
        r"\b(?:preciso|precisamos|vou precisar)\s+(?:de|que voce envie)\s+(?:mais\s+)?"
        r"(?:dados|detalhes|informacoes)\b"
    ),
    re.compile(r"\b(?:para|pra)\s+(?:eu|nos)\s+(?:continuar|analisar|investigar|te orientar|verificar)\b"),
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


def enforce_resolution_semantics(decision: SupervisorDecision) -> SupervisorDecision:
    """Downgrade a non-conclusive ``candidate_resolved`` decision safely."""
    if decision.outcome != "candidate_resolved":
        return decision

    signals = customer_input_signals(decision.final_response)
    if not signals:
        return decision

    risk_flags = list(dict.fromkeys([*decision.risk_flags, "candidate_resolution_requires_customer_input"]))
    trace_summary = list(
        dict.fromkeys(
            [
                *decision.trace_summary,
                "resolution_policy: downgraded_to_waiting_customer",
                *(f"resolution_policy: {signal}" for signal in signals),
            ]
        )
    )
    return decision.model_copy(
        update={
            "outcome": "waiting_customer",
            "risk_flags": risk_flags,
            "trace_summary": trace_summary,
        }
    )


__all__ = ["customer_input_signals", "enforce_resolution_semantics"]
