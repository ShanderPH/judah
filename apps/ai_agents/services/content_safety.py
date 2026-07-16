"""Deterministic safety checks for untrusted customer content."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CUSTOMER_TEXT_LENGTH = 12_000

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore (all |any )?(previous|prior|above) instructions?\b", re.IGNORECASE),
    re.compile(r"\b(disregard|override) (the )?(system|developer) (prompt|instructions?)\b", re.IGNORECASE),
    re.compile(r"\b(reveal|show|print|repeat) (the )?(system|developer) prompt\b", re.IGNORECASE),
    re.compile(r"\bignore (todas? |quaisquer )?(as )?instru[cç][oõ]es anteriores\b", re.IGNORECASE),
    re.compile(r"\b(desconsidere|substitua) (o )?(prompt|instru[cç][oõ]es) (do sistema|anteriores)\b", re.IGNORECASE),
    re.compile(r"\b(mostre|revele|imprima|repita) (o )?prompt (do sistema|de desenvolvedor)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ContentSafetyAssessment:
    """Sanitized text plus deterministic risk signals."""

    sanitized_text: str
    risk_flags: tuple[str, ...]
    requires_handoff: bool


def assess_customer_content(text: str) -> ContentSafetyAssessment:
    """Normalize customer text and flag explicit instruction-override attempts."""
    sanitized = "".join(character for character in text if character in "\n\r\t" or character.isprintable()).strip()
    risk_flags: list[str] = []

    if len(sanitized) > MAX_CUSTOMER_TEXT_LENGTH:
        sanitized = sanitized[:MAX_CUSTOMER_TEXT_LENGTH]
        risk_flags.append("content_truncated")

    if any(pattern.search(sanitized) for pattern in _PROMPT_INJECTION_PATTERNS):
        risk_flags.append("prompt_injection_attempt")

    return ContentSafetyAssessment(
        sanitized_text=sanitized,
        risk_flags=tuple(risk_flags),
        requires_handoff="prompt_injection_attempt" in risk_flags,
    )


__all__ = ["ContentSafetyAssessment", "assess_customer_content"]
