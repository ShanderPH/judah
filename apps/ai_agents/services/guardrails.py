"""Deterministic input/output guardrails for customer-facing AI turns."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    text: str
    risk_flags: list[str]
    redaction_count: int = 0


_REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("cpf_redacted", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF REDACTED]"),
    (
        "email_redacted",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[EMAIL REDACTED]",
    ),
    (
        "credential_redacted",
        re.compile(r"\b(?:sk-(?:proj-)?|pat-[a-z0-9]+-)[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
        "[CREDENTIAL REDACTED]",
    ),
    (
        "bearer_token_redacted",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*", re.IGNORECASE),
        "Bearer [TOKEN REDACTED]",
    ),
)

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all |any )?(?:previous|prior) instructions", re.IGNORECASE),
    re.compile(r"ignore (?:as |todas as )?(?:instru[cç][oõ]es|regras) anteriores", re.IGNORECASE),
    re.compile(r"(?:reveal|show|expose|mostre|revele).{0,30}(?:system prompt|prompt do sistema)", re.IGNORECASE),
    re.compile(r"(?:developer|system) message", re.IGNORECASE),
    re.compile(r"jailbreak|modo desenvolvedor", re.IGNORECASE),
)


def _normalize_text(value: str, *, max_chars: int) -> tuple[str, list[str]]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = "".join(char for char in normalized if char in "\n\t" or unicodedata.category(char) != "Cc")
    flags: list[str] = []
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars]
        flags.append("content_truncated")
    return normalized.strip(), flags


def _redact(value: str) -> tuple[str, list[str], int]:
    flags: list[str] = []
    count = 0
    for flag, pattern, replacement in _REDACTION_PATTERNS:
        value, replacements = pattern.subn(replacement, value)
        if replacements:
            flags.append(flag)
            count += replacements
    return value, flags, count


def apply_input_guardrails(value: str, *, max_chars: int = 12_000) -> GuardrailResult:
    """Normalize untrusted customer content and redact common sensitive values."""
    text, flags = _normalize_text(value, max_chars=max_chars)
    text, redaction_flags, redaction_count = _redact(text)
    flags.extend(redaction_flags)
    if len(text) > max_chars:
        text = text[:max_chars]
        flags.append("content_truncated")
    if any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS):
        flags.append("prompt_injection_detected")
    return GuardrailResult(text=text, risk_flags=list(dict.fromkeys(flags)), redaction_count=redaction_count)


def apply_output_guardrails(value: str, *, max_chars: int = 4_000) -> GuardrailResult:
    """Prevent a provider response from echoing sensitive values to the customer."""
    text, flags = _normalize_text(value, max_chars=max_chars)
    text, redaction_flags, redaction_count = _redact(text)
    flags.extend(redaction_flags)
    if len(text) > max_chars:
        text = text[:max_chars]
        flags.append("content_truncated")
    if not text:
        flags.append("empty_output")
    return GuardrailResult(text=text, risk_flags=list(dict.fromkeys(flags)), redaction_count=redaction_count)


__all__ = ["GuardrailResult", "apply_input_guardrails", "apply_output_guardrails"]
